"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license."""

import logging

from core.feature_flags import flag_set
from core.mixins import GetParentObjectMixin
from core.permissions import ViewClassPermission, all_permissions
from core.utils.common import is_community
from core.utils.params import bool_from_request
from data_manager.api import TaskListAPI as DMTaskListAPI
from data_manager.functions import evaluate_predictions
from data_manager.models import PrepareParams
from data_manager.serializers import DataManagerTaskSerializer
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.decorators import method_decorator
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from projects.functions.stream_history import fill_history_annotation
from projects.models import Project
from rest_framework import generics, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from tasks.choices import ActionType, ReviewResult
from tasks.mixins import can_review
from tasks.models import Annotation, AnnotationDraft, AnnotationReview, Prediction, Task
from tasks.openapi_schema import (
    annotation_request_schema,
    annotation_response_example,
    dm_task_response_example,
    prediction_request_schema,
    prediction_response_example,
    task_request_schema,
    task_response_example,
)
from tasks.serializers import (
    AnnotationDraftSerializer,
    AnnotationReviewSerializer,
    AnnotationSerializer,
    PredictionSerializer,
    TaskSerializer,
    TaskSimpleSerializer,
)
from webhooks.models import WebhookAction
from webhooks.utils import (
    api_webhook,
    api_webhook_for_delete,
    emit_webhooks_for_instance,
)

logger = logging.getLogger(__name__)


# TODO: fix after switch to api/tasks from api/dm/tasks
@method_decorator(
    name='post',
    decorator=extend_schema(
        tags=['Tasks'],
        summary='Create task',
        description='Create a new labeling task in Label Studio.',
        request={
            'application/json': task_request_schema,
        },
        responses={
            '201': OpenApiResponse(
                description='Created task',
                response=TaskSerializer,
                examples=[OpenApiExample(name='response', value=task_response_example, media_type='application/json')],
            )
        },
        extensions={
            'x-fern-sdk-group-name': 'tasks',
            'x-fern-sdk-method-name': 'create',
            'x-fern-audiences': ['public'],
        },
    )
    if is_community()
    else lambda f: f,
)
@method_decorator(
    name='get',
    decorator=extend_schema(
        tags=['Tasks'],
        summary='Get tasks list',
        description="""
    Retrieve a list of tasks with pagination for a specific view or project, by using filters and ordering.
    """,
        parameters=[
            OpenApiParameter(name='view', type=OpenApiTypes.INT, location='query', description='View ID'),
            OpenApiParameter(name='project', type=OpenApiTypes.INT, location='query', description='Project ID'),
            OpenApiParameter(
                name='resolve_uri',
                type=OpenApiTypes.BOOL,
                location='query',
                description='Resolve task data URIs using Cloud Storage',
            ),
            OpenApiParameter(
                name='fields',
                type=OpenApiTypes.STR,
                enum=['all', 'task_only'],
                default='task_only',
                location='query',
                description='Set to "all" if you want to include annotations and predictions in the response',
            ),
            OpenApiParameter(
                name='review',
                type=OpenApiTypes.BOOL,
                location='query',
                description='Get tasks for review',
            ),
            OpenApiParameter(
                name='include',
                type=OpenApiTypes.STR,
                location='query',
                description='Specify which fields to include in the response',
            ),
            OpenApiParameter(
                name='query',
                type=OpenApiTypes.STR,
                location='query',
                description='Additional query to filter tasks. It must be JSON encoded string of dict containing '
                'one of the following parameters: `{"filters": ..., "selectedItems": ..., "ordering": ...}`. Check '
                '[Data Manager > Create View > see `data` field](#tag/Data-Manager/operation/api_dm_views_create) '
                'for more details about filters, selectedItems and ordering.\n\n'
                '* **filters**: dict with `"conjunction"` string (`"or"` or `"and"`) and list of filters in `"items"` array. '
                'Each filter is a dictionary with keys: `"filter"`, `"operator"`, `"type"`, `"value"`. '
                '[Read more about available filters](https://labelstud.io/sdk/data_manager.html)<br/>'
                '                   Example: `{"conjunction": "or", "items": [{"filter": "filter:tasks:completed_at", "operator": "greater", "type": "Datetime", "value": "2021-01-01T00:00:00.000Z"}]}`\n'
                '* **selectedItems**: dictionary with keys: `"all"`, `"included"`, `"excluded"`. If "all" is `false`, `"included"` must be used. If "all" is `true`, `"excluded"` must be used.<br/>'
                '                   Examples: `{"all": false, "included": [1, 2, 3]}` or `{"all": true, "excluded": [4, 5]}`\n'
                '* **ordering**: list of fields to order by. Currently, ordering is supported by only one parameter. <br/>\n'
                '                   Example: `["completed_at"]`',
            ),
        ],
        responses={
            '200': OpenApiResponse(
                description='Tasks list',
                response={
                    'type': 'object',
                    'properties': {
                        'tasks': {
                            'description': 'List of tasks',
                            'type': 'array',
                            'items': {
                                'description': 'Task object',
                                'type': 'object',
                            },
                        },
                        'total': {
                            'description': 'Total number of tasks',
                            'type': 'integer',
                        },
                        'total_annotations': {
                            'description': 'Total number of annotations',
                            'type': 'integer',
                        },
                        'total_predictions': {
                            'description': 'Total number of predictions',
                            'type': 'integer',
                        },
                    },
                },
            )
        },
        extensions={
            'x-fern-sdk-group-name': 'tasks',
            'x-fern-sdk-method-name': 'list',
            'x-fern-pagination': {
                'offset': '$request.page',
                'results': '$response.tasks',
            },
            'x-fern-audiences': ['public'],
        },
    )
    if is_community()
    else lambda f: f,
)
class TaskListAPI(DMTaskListAPI):
    serializer_class = TaskSerializer
    permission_required = ViewClassPermission(
        GET=all_permissions.tasks_view,
        POST=all_permissions.tasks_create,
    )
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['project']

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        return queryset.filter(project__organization=self.request.user.active_organization)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        project_id = self.request.data.get('project')
        if project_id:
            context['project'] = generics.get_object_or_404(Project, pk=project_id)
        return context

    def perform_create(self, serializer):
        project_id = self.request.data.get('project')
        project = generics.get_object_or_404(Project, pk=project_id)
        instance = serializer.save(project=project)
        emit_webhooks_for_instance(
            self.request.user.active_organization, project, WebhookAction.TASKS_CREATED, [instance]
        )


@method_decorator(
    name='get',
    decorator=extend_schema(
        tags=['Tasks'],
        summary='Get task',
        description="""
        Get task data, metadata, annotations and other attributes for a specific labeling task by task ID.
        """,
        parameters=[
            OpenApiParameter(name='id', type=OpenApiTypes.STR, location='path', description='Task ID'),
        ],
        request=None,
        responses={
            '200': OpenApiResponse(
                description='Task',
                response=DataManagerTaskSerializer,
                examples=[
                    OpenApiExample(name='response', value=dm_task_response_example, media_type='application/json')
                ],
            )
        },
        extensions={
            'x-fern-sdk-group-name': 'tasks',
            'x-fern-sdk-method-name': 'get',
            'x-fern-audiences': ['public'],
        },
    ),
)
@method_decorator(
    name='patch',
    decorator=extend_schema(
        tags=['Tasks'],
        summary='Update task',
        description='Update the attributes of an existing labeling task.',
        parameters=[
            OpenApiParameter(name='id', type=OpenApiTypes.STR, location='path', description='Task ID'),
        ],
        request={
            'application/json': task_request_schema,
        },
        responses={
            '200': OpenApiResponse(
                description='Updated task',
                response=TaskSerializer,
                examples=[OpenApiExample(name='response', value=task_response_example, media_type='application/json')],
            )
        },
        extensions={
            'x-fern-sdk-group-name': 'tasks',
            'x-fern-sdk-method-name': 'update',
            'x-fern-audiences': ['public'],
        },
    ),
)
@method_decorator(
    name='delete',
    decorator=extend_schema(
        tags=['Tasks'],
        summary='Delete task',
        description='Delete a task in Label Studio. This action cannot be undone!',
        parameters=[
            OpenApiParameter(name='id', type=OpenApiTypes.STR, location='path', description='Task ID'),
        ],
        request=None,
        extensions={
            'x-fern-sdk-group-name': 'tasks',
            'x-fern-sdk-method-name': 'delete',
            'x-fern-audiences': ['public'],
        },
    ),
)
class TaskAPI(generics.RetrieveUpdateDestroyAPIView):
    parser_classes = (JSONParser, FormParser, MultiPartParser)
    permission_required = ViewClassPermission(
        GET=all_permissions.tasks_view,
        PUT=all_permissions.tasks_change,
        PATCH=all_permissions.tasks_change,
        DELETE=all_permissions.tasks_delete,
    )

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.task = self.get_object()

    def prefetch(self, queryset):
        prefetch_fields = [
            'annotations',
            'predictions',
            'annotations__completed_by',
            'project',
            'io_storages_azureblobimportstoragelink',
            'io_storages_gcsimportstoragelink',
            'io_storages_localfilesimportstoragelink',
            'io_storages_redisimportstoragelink',
            'io_storages_s3importstoragelink',
            'file_upload',
            'project__ml_backends',
        ]
        # review mode needs nested review records on annotations
        if bool_from_request(self.request.GET, 'review', False):
            prefetch_fields += ['annotations__reviews', 'annotations__reviews__created_by']
        return queryset.prefetch_related(*prefetch_fields)

    def get_retrieve_serializer_context(self, request):
        """Build serializer context for task retrieval.

        The resolve_uri parameter controls whether storage URLs (e.g., s3://bucket/file.jpg)
        are converted to proxy URLs (/tasks/<id>/resolve/?fileuri=...). This is useful for:
        - resolve_uri=True (default): URLs are proxied through Label Studio for security
        - resolve_uri=False: Original storage URLs are preserved, useful for debugging
          or when users need to see the actual source paths in task preview
        """
        fields = ['drafts', 'predictions', 'annotations']

        # Lazy load annotations behind feature flag (FIT-720)
        annotations_stub = False
        if flag_set('fflag_fix_all_fit_720_lazy_load_annotations', user=request.user):
            annotations_stub = bool_from_request(request.GET, 'annotations_stub', False)

        return {
            'resolve_uri': bool_from_request(request.GET, 'resolve_uri', True),
            'predictions': 'predictions' in fields,
            'annotations': 'annotations' in fields,
            'drafts': 'drafts' in fields,
            'annotations_stub': annotations_stub,
            'request': request,
        }

    def get(self, request, pk):
        context = self.get_retrieve_serializer_context(request)
        context['project'] = project = self.task.project

        # get prediction
        if (
            project.evaluate_predictions_automatically or project.show_collab_predictions
        ) and not self.task.predictions.exists():
            evaluate_predictions([self.task])
            # refresh task from db with prefetches
            self.task = self.get_object()

        # Don't use expand for annotations when using stub mode (FIT-720)
        # The expand mechanism would override get_annotations and use AnnotationSerializer
        # instead of AnnotationStubSerializer
        expand = [] if context.get('annotations_stub') else ['annotations.completed_by']
        # review mode: nest full review records (reviewer + result + comment)
        if bool_from_request(request.GET, 'review', False):
            expand += ['annotations.reviews']
        serializer = self.get_serializer_class()(self.task, many=False, context=context, expand=expand)
        data = serializer.data
        return Response(data)

    def get_excluded_fields_for_evaluation(self):
        return ['annotations_results', 'predictions_results']

    def get_queryset(self):
        task_id = self.request.parser_context['kwargs'].get('pk')
        task = generics.get_object_or_404(Task, pk=task_id)
        review = bool_from_request(self.request.GET, 'review', False)
        selected = {'all': False, 'included': [self.kwargs.get('pk')]}
        if review:
            kwargs = {'fields_for_evaluation': ['annotators', 'reviewed']}
        else:
            kwargs = {
                'all_fields': True,
                'excluded_fields_for_evaluation': self.get_excluded_fields_for_evaluation(),
            }
        project = self.request.query_params.get('project') or self.request.data.get('project')
        if not project:
            project = task.project.id
        return self.prefetch(
            Task.prepared.get_queryset(
                prepare_params=PrepareParams(project=project, selectedItems=selected, request=self.request), **kwargs
            )
        )

    def get_object(self):
        """
        Override to check permissions on a lightweight task first.

        This avoids executing the expensive PreparedTaskManager query
        when the user doesn't have permission to access the task.
        """
        task_id = self.kwargs.get('pk')

        # First check permissions using a lightweight query
        # select_related('project') avoids extra query when permission check accesses task.project
        lean_task = generics.get_object_or_404(
            Task.objects.filter(project__organization=self.request.user.active_organization).select_related('project'),
            pk=task_id,
        )
        self.check_object_permissions(self.request, lean_task)

        # Now fetch full task with heavy queryset (prefetches, annotations, etc.)
        queryset = self.filter_queryset(self.get_queryset())
        return generics.get_object_or_404(queryset, pk=task_id)

    def get_serializer_class(self):
        # GET => task + annotations + predictions + drafts
        if self.request.method == 'GET':
            return DataManagerTaskSerializer

        # POST, PATCH, PUT
        else:
            return TaskSimpleSerializer

    def patch(self, request, *args, **kwargs):
        return super(TaskAPI, self).patch(request, *args, **kwargs)

    @api_webhook_for_delete(WebhookAction.TASKS_DELETED)
    def delete(self, request, *args, **kwargs):
        return super(TaskAPI, self).delete(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def put(self, request, *args, **kwargs):
        return super(TaskAPI, self).put(request, *args, **kwargs)


@method_decorator(
    name='get',
    decorator=extend_schema(
        tags=['Tasks'],
        summary='Get task label distribution',
        description='Get aggregated label distribution across all annotations for a task. '
        'Returns counts of each label value grouped by control tag. '
        'This is an efficient endpoint that avoids N+1 queries.',
        responses={
            '200': OpenApiResponse(
                description='Label distribution data',
                examples=[
                    OpenApiExample(
                        name='response',
                        value={
                            'total_annotations': 100,
                            'distributions': {
                                'label': {
                                    'type': 'rectanglelabels',
                                    'labels': {'Car': 45, 'Person': 30, 'Dog': 25},
                                },
                            },
                        },
                        media_type='application/json',
                    )
                ],
            )
        },
        extensions={
            'x-fern-audiences': ['internal'],
        },
    ),
)
class TaskAgreementAPI(generics.RetrieveAPIView):
    """
    Efficient endpoint for getting label distribution without fetching all annotations.

    This endpoint aggregates annotation results at the database level to avoid N+1 queries.
    It returns pre-computed label counts for the Distribution row in the Summary view.
    """

    permission_required = ViewClassPermission(GET=all_permissions.tasks_view)
    queryset = Task.objects.all()

    def get(self, request, pk):
        # This endpoint is gated by feature flag
        if not flag_set('fflag_fix_all_fit_720_lazy_load_annotations', user=request.user):
            raise PermissionDenied('Feature not enabled')

        try:
            task = Task.objects.get(pk=pk)
        except Task.DoesNotExist:
            return Response({'error': 'Task not found'}, status=404)

        # Check project access using LSO's native permission check
        if not task.project.has_permission(request.user):
            raise PermissionDenied('You do not have permission to view this task')

        # Get all annotations for this task with their results in a single query
        annotations = Annotation.objects.filter(
            task=task,
            was_cancelled=False,
        ).values_list('result', flat=True)

        total_annotations = len(annotations)
        distributions = {}

        def merge_result_into_distributions(result):
            """Merge a single result (list of labeling items) into distributions in place."""
            if not result or not isinstance(result, list):
                return
            for item in result:
                if not isinstance(item, dict):
                    continue
                from_name = item.get('from_name', '')
                result_type = item.get('type', '')
                value = item.get('value', {})

                if from_name not in distributions:
                    distributions[from_name] = {
                        'type': result_type,
                        'labels': {},
                        'values': [],
                    }

                if result_type.endswith('labels'):
                    labels = value.get(result_type, [])
                    if isinstance(labels, list):
                        for label in labels:
                            if label not in distributions[from_name]['labels']:
                                distributions[from_name]['labels'][label] = 0
                            distributions[from_name]['labels'][label] += 1

                elif result_type == 'choices':
                    choices = value.get('choices', [])
                    if isinstance(choices, list):
                        for choice in choices:
                            if choice not in distributions[from_name]['labels']:
                                distributions[from_name]['labels'][choice] = 0
                            distributions[from_name]['labels'][choice] += 1

                elif result_type == 'rating':
                    rating = value.get('rating')
                    if rating is not None:
                        distributions[from_name]['values'].append(rating)

                elif result_type == 'number':
                    number = value.get('number')
                    if number is not None:
                        distributions[from_name]['values'].append(number)

                elif result_type == 'taxonomy':
                    taxonomy = value.get('taxonomy', [])
                    if isinstance(taxonomy, list):
                        for path in taxonomy:
                            if isinstance(path, list) and path:
                                leaf = path[-1]
                                if leaf not in distributions[from_name]['labels']:
                                    distributions[from_name]['labels'][leaf] = 0
                                distributions[from_name]['labels'][leaf] += 1

                elif result_type == 'pairwise':
                    selected = value.get('selected')
                    if selected:
                        if selected not in distributions[from_name]['labels']:
                            distributions[from_name]['labels'][selected] = 0
                        distributions[from_name]['labels'][selected] += 1

        # Process annotation results
        for result in annotations:
            merge_result_into_distributions(result)

        # Include prediction results in distribution counts so aggregate matches
        # client-side (develop / FF off). total_annotations stays annotation count only.
        predictions = Prediction.objects.filter(task=task).values_list('result', flat=True)
        for result in predictions:
            # Prediction.result can be list (same as annotation) or dict
            if isinstance(result, list):
                merge_result_into_distributions(result)

        # Post-process: calculate averages for numeric types
        for from_name, dist in distributions.items():
            if dist['values']:
                dist['average'] = sum(dist['values']) / len(dist['values'])
                dist['count'] = len(dist['values'])
            # Remove raw values from response to keep it lightweight
            del dist['values']

        return Response(
            {
                'total_annotations': total_annotations,
                'distributions': distributions,
            }
        )


@method_decorator(
    name='get',
    decorator=extend_schema(
        tags=['Annotations'],
        summary='Get annotation by its ID',
        description='Retrieve a specific annotation for a task using the annotation result ID.',
        request=None,
        responses={
            '200': OpenApiResponse(
                description='Retrieved annotation',
                response=AnnotationSerializer,
                examples=[
                    OpenApiExample(name='response', value=annotation_response_example, media_type='application/json')
                ],
            )
        },
        extensions={
            'x-fern-sdk-group-name': 'annotations',
            'x-fern-sdk-method-name': 'get',
            'x-fern-audiences': ['public'],
        },
    ),
)
@method_decorator(
    name='patch',
    decorator=extend_schema(
        tags=['Annotations'],
        summary='Update annotation',
        description='Update existing attributes on an annotation.',
        request={
            'application/json': annotation_request_schema,
        },
        responses={
            '200': OpenApiResponse(
                description='Updated annotation',
                response=AnnotationSerializer,
                examples=[
                    OpenApiExample(name='response', value=annotation_response_example, media_type='application/json')
                ],
            )
        },
        extensions={
            'x-fern-sdk-group-name': 'annotations',
            'x-fern-sdk-method-name': 'update',
            'x-fern-audiences': ['public'],
        },
    ),
)
@method_decorator(
    name='delete',
    decorator=extend_schema(
        tags=['Annotations'],
        summary='Delete annotation',
        description="Delete an annotation. This action can't be undone!",
        request=None,
        extensions={
            'x-fern-sdk-group-name': 'annotations',
            'x-fern-sdk-method-name': 'delete',
            'x-fern-audiences': ['public'],
        },
    ),
)
class AnnotationAPI(generics.RetrieveUpdateDestroyAPIView):
    parser_classes = (JSONParser, FormParser, MultiPartParser)
    permission_required = ViewClassPermission(
        GET=all_permissions.annotations_view,
        PUT=all_permissions.annotations_change,
        PATCH=all_permissions.annotations_change,
        DELETE=all_permissions.annotations_delete,
    )

    serializer_class = AnnotationSerializer
    queryset = Annotation.objects.all()

    def perform_destroy(self, annotation):
        annotation.delete()

    def update(self, request, *args, **kwargs):
        # save user history with annotator_id, time & annotation result
        annotation = self.get_object()
        # use updated instead of save to avoid duplicated signals
        Annotation.objects.filter(id=annotation.id).update(updated_by=request.user)

        task = annotation.task
        if self.request.data.get('ground_truth'):
            task.ensure_unique_groundtruth(annotation_id=annotation.id)
        task.update_is_labeled()
        task.save()  # refresh task metrics

        result = super(AnnotationAPI, self).update(request, *args, **kwargs)

        task.update_is_labeled()
        task.save(update_fields=['updated_at'])  # refresh task metrics
        return result

    def get(self, request, *args, **kwargs):
        return super(AnnotationAPI, self).get(request, *args, **kwargs)

    @api_webhook(WebhookAction.ANNOTATION_UPDATED)
    @extend_schema(exclude=True)
    def put(self, request, *args, **kwargs):
        return super(AnnotationAPI, self).put(request, *args, **kwargs)

    @api_webhook(WebhookAction.ANNOTATION_UPDATED)
    def patch(self, request, *args, **kwargs):
        return super(AnnotationAPI, self).patch(request, *args, **kwargs)

    @api_webhook_for_delete(WebhookAction.ANNOTATIONS_DELETED)
    def delete(self, request, *args, **kwargs):
        return super(AnnotationAPI, self).delete(request, *args, **kwargs)


REVIEW_TRANSITION_BY_RESULT = {
    ReviewResult.ACCEPTED: 'annotation_accepted',
    ReviewResult.REJECTED: 'annotation_rejected',
    ReviewResult.FIXED_AND_ACCEPTED: 'annotation_fixed_and_accepted',
}


def _fire_review_transition(annotation, transition_name, user, context_data=None):
    """Execute an FSM review transition on the annotation, degrading gracefully.

    Reviews must work even when the FSM feature is off or misconfigured, so any
    transition failure is logged and swallowed (the last_action field remains
    the source of truth for `accepted_state`).
    """
    try:
        from fsm.utils import is_fsm_enabled

        if not is_fsm_enabled(user):
            return
        from fsm.state_manager import StateManager

        StateManager.execute_transition(
            entity=annotation,
            transition_name=transition_name,
            user=user,
            context_data=context_data or {},
        )
    except Exception as exc:  # noqa: BLE001 - FSM must never break the review flow
        logger.warning('Review transition %s failed for annotation %s: %s', transition_name, annotation.id, exc)


def _apply_review_result_to_annotation(annotation, review_result, user, annotation_result=None):
    """Persist the review outcome onto the annotation.

    Sets `last_action` (consumed as `accepted_state` by the editor) and, when a
    new `annotation_result` is supplied (fix-and-accept), atomically replaces the
    annotation's labeling result.
    """
    if annotation_result is not None:
        if not isinstance(annotation_result, list):
            raise ValidationError({'annotation_result': 'Annotation result must be a list'})
        annotation.result = annotation_result
    annotation.last_action = review_result
    annotation.updated_by = user
    annotation.save()


class AnnotationReviewListAPI(generics.ListCreateAPIView):
    """List and create reviews for a single annotation.

    GET  /api/annotations/<id>/reviews/ - list of review records
    POST /api/annotations/<id>/reviews/ - create (upsert per reviewer) a review

    POST body:
      {
        "result": "accepted" | "rejected" | "fixed_and_accepted",
        "comment": "optional review comment",
        "annotation_result": [...]   // optional - replaces annotation result (fix-and-accept)
      }

    EE-compatible aliases are also accepted: `"accepted": true|false` and
    `result: "fixed"`.
    """

    parser_classes = (JSONParser, FormParser, MultiPartParser)
    permission_required = ViewClassPermission(
        GET=all_permissions.annotations_view,
        POST=all_permissions.annotations_change,
    )
    serializer_class = AnnotationReviewSerializer

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.annotation = self.get_annotation()

    def get_annotation(self):
        annotation = generics.get_object_or_404(
            Annotation.objects.select_related('task', 'task__project', 'completed_by'),
            pk=self.kwargs['pk'],
        )
        # object-level permission: task scoping for assigned annotators lives in
        # AnnotationMixin.has_permission / TaskMixin.has_permission
        self.check_object_permissions(self.request, annotation)
        return annotation

    def get_queryset(self):
        return self.annotation.reviews.select_related('created_by').order_by('pk')

    def check_can_review(self, annotation):
        user = self.request.user
        if not can_review(user, annotation.task):
            raise PermissionDenied('You do not have permission to review annotations in this project')
        if annotation.completed_by_id == user.id:
            raise ValidationError({'detail': 'You cannot review your own annotation'})

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        annotation = self.annotation
        self.check_can_review(annotation)

        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result_value = data.get('result')
        if result_value not in ReviewResult.values:
            raise ValidationError({'result': 'Expected one of: accepted, rejected, fixed_and_accepted'})

        annotation_result = request.data.get('annotation_result', None)
        if annotation_result is not None:
            # any result override is by definition a fix-and-accept
            result_value = ReviewResult.FIXED_AND_ACCEPTED

        _apply_review_result_to_annotation(annotation, result_value, request.user, annotation_result)

        review, created = AnnotationReview.objects.update_or_create(
            annotation=annotation,
            created_by=request.user,
            defaults={'result': result_value, 'comment': data.get('comment')},
        )

        _fire_review_transition(
            annotation,
            REVIEW_TRANSITION_BY_RESULT[result_value],
            request.user,
            context_data={'review_id': review.id, 'result': result_value},
        )

        return Response(self.get_serializer(review).data, status=201 if created else 200)


class AnnotationReviewAPI(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a single review record.

    GET    /api/annotation-reviews/<id>/
    PATCH  /api/annotation-reviews/<id>/  - {result?, comment?, annotation_result?}
    DELETE /api/annotation-reviews/<id>/  - removes the review and resets the
                                          annotation's review state
    """

    parser_classes = (JSONParser, FormParser, MultiPartParser)
    permission_required = ViewClassPermission(
        GET=all_permissions.annotations_view,
        PATCH=all_permissions.annotations_change,
        DELETE=all_permissions.annotations_change,
    )
    serializer_class = AnnotationReviewSerializer
    queryset = AnnotationReview.objects.select_related(
        'annotation', 'annotation__task', 'annotation__task__project', 'created_by'
    )

    def _can_modify(self, review, user):
        """Authors may modify their own reviews; management roles may modify any."""
        if review.created_by_id == user.id:
            return True
        if not can_review(user, review.annotation.task):
            return False
        # org reviewers may only touch their own reviews
        if getattr(user, 'is_reviewer', False) or getattr(user, 'is_annotator', False):
            return False
        return True

    def get_object(self):
        review = super().get_object()
        if self.request.method != 'GET' and not self._can_modify(review, self.request.user):
            raise PermissionDenied('Only the review author or a manager may modify this review')
        return review

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        review = self.get_object()
        annotation = review.annotation

        serializer = self.get_serializer(review, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        annotation_result = request.data.get('annotation_result', None)
        result_value = data.get('result')
        if annotation_result is not None:
            result_value = ReviewResult.FIXED_AND_ACCEPTED
        if result_value is None:
            result_value = review.result

        if 'comment' in data:
            review.comment = data['comment']
        review.result = result_value
        review.save(update_fields=['result', 'comment', 'updated_at'])

        _apply_review_result_to_annotation(annotation, result_value, request.user, annotation_result)
        _fire_review_transition(
            annotation,
            REVIEW_TRANSITION_BY_RESULT.get(result_value, 'annotation_accepted'),
            request.user,
            context_data={'review_id': review.id, 'result': result_value},
        )
        return Response(self.get_serializer(review).data)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        review = self.get_object()
        annotation = review.annotation
        review.delete()

        # unreview: the annotation returns to "not reviewed" via last_action
        _apply_review_result_to_annotation(annotation, ActionType.DELETED_REVIEW, request.user)
        _fire_review_transition(
            annotation,
            'annotation_review_deleted',
            request.user,
            context_data={'deleted_review_id': review.id},
        )
        return Response(status=204)


@method_decorator(
    name='get',
    decorator=extend_schema(
        tags=['Annotations'],
        summary='Get all task annotations',
        description='List all annotations for a task.',
        parameters=[
            OpenApiParameter(name='id', type=OpenApiTypes.INT, location='path', description='Task ID'),
        ],
        request=None,
        responses={
            '200': OpenApiResponse(
                description='Annotation',
                response=AnnotationSerializer(many=True),
                examples=[
                    OpenApiExample(name='response', value=[annotation_response_example], media_type='application/json')
                ],
            )
        },
        extensions={
            'x-fern-sdk-group-name': 'annotations',
            'x-fern-sdk-method-name': 'list',
            'x-fern-audiences': ['public'],
        },
    ),
)
@method_decorator(
    name='post',
    decorator=extend_schema(
        tags=['Annotations'],
        summary='Create annotation',
        description="""
        Add annotations to a task like an annotator does. The content of the result field depends on your
        labeling configuration. For example, send the following data as part of your POST
        request to send an empty annotation with the ID of the user who completed the task:

        ```json
        {
        "result": {},
        "was_cancelled": true,
        "ground_truth": true,
        "lead_time": 0,
        "task": 0
        "completed_by": 123
        }
        ```
        """,
        parameters=[
            OpenApiParameter(name='id', type=OpenApiTypes.INT, location='path', description='Task ID'),
        ],
        request={
            'application/json': annotation_request_schema,
        },
        responses={
            '201': OpenApiResponse(
                description='Created annotation',
                response=AnnotationSerializer,
                examples=[
                    OpenApiExample(name='response', value=annotation_response_example, media_type='application/json')
                ],
            )
        },
        extensions={
            'x-fern-sdk-group-name': 'annotations',
            'x-fern-sdk-method-name': 'create',
            'x-fern-audiences': ['public'],
        },
    ),
)
class AnnotationsListAPI(GetParentObjectMixin, generics.ListCreateAPIView):
    parser_classes = (JSONParser, FormParser, MultiPartParser)
    permission_required = ViewClassPermission(
        GET=all_permissions.annotations_view,
        POST=all_permissions.annotations_create,
    )
    parent_queryset = Task.objects.all()

    serializer_class = AnnotationSerializer

    def get(self, request, *args, **kwargs):
        return super(AnnotationsListAPI, self).get(request, *args, **kwargs)

    @api_webhook(WebhookAction.ANNOTATION_CREATED)
    def post(self, request, *args, **kwargs):
        return super(AnnotationsListAPI, self).post(request, *args, **kwargs)

    def get_queryset(self):
        task = generics.get_object_or_404(Task.objects.for_user(self.request.user), pk=self.kwargs.get('pk', 0))
        # enforce task-level permissions (manual assignment scoping for annotators)
        self.check_object_permissions(self.request, task)
        return Annotation.objects.filter(Q(task=task) & Q(was_cancelled=False)).order_by('pk')

    def delete_draft(self, draft_id, annotation_id):
        try:
            draft = AnnotationDraft.objects.get(id=draft_id)
            # We call delete on the individual draft object because
            # AnnotationDraft#delete has special behavior (updating created_labels_drafts).
            # This special behavior won't be triggered if we call delete on the queryset.
            # Only for drafts with empty annotation_id, other ones deleted by signal
            draft.delete()
        except AnnotationDraft.DoesNotExist:
            pass

    def perform_create(self, ser):
        task = self.parent_object
        # annotator has write access only to annotations and it can't be checked it after serializer.save()
        user = self.request.user

        # Check if task is being skipped and if it's allowed
        was_cancelled_get = bool_from_request(self.request.GET, 'was_cancelled', False)
        was_cancelled_data = self.request.data.get('was_cancelled', False)
        is_skipping = was_cancelled_get or was_cancelled_data

        if is_skipping and not task.can_be_skipped():
            raise ValidationError({'detail': 'This task cannot be skipped.'})

        # updates history
        result = ser.validated_data.get('result')
        extra_args = {'task_id': self.kwargs['pk'], 'project_id': task.project_id}

        # save stats about how well annotator annotations coincide with current prediction
        # only for finished task annotations
        if result is not None:
            prediction = Prediction.objects.filter(task=task, model_version=task.project.model_version)
            if prediction.exists():
                prediction = prediction.first()
                prediction_ser = PredictionSerializer(prediction).data
            else:
                logger.debug(f'User={self.request.user}: there are no predictions for task={task}')
                prediction_ser = {}
            # serialize annotation
            extra_args.update({'prediction': prediction_ser, 'updated_by': user})

        if 'was_cancelled' in self.request.GET:
            extra_args['was_cancelled'] = bool_from_request(self.request.GET, 'was_cancelled', False)

        if 'completed_by' not in ser.validated_data:
            extra_args['completed_by'] = self.request.user

        draft_id = self.request.data.get('draft_id')
        draft = AnnotationDraft.objects.filter(id=draft_id).first()
        if draft:
            # draft permission check
            if draft.task_id != task.id or not draft.has_permission(user) or draft.user_id != user.id:
                raise PermissionDenied(f'You have no permission to draft id:{draft_id}')

        if draft is not None:
            # if the annotation will be created from draft - get created_at from draft to keep continuity of history
            extra_args['draft_created_at'] = draft.created_at

        # create annotation
        logger.debug(f'User={self.request.user}: save annotation')
        annotation = ser.save(**extra_args)

        logger.debug(f'Save activity for user={self.request.user}')
        self.request.user.activity_at = timezone.now()
        self.request.user.save()

        # Release task if it has been taken at work (it should be taken by the same user, or it makes sentry error
        logger.debug(f'User={user} releases task={task}')
        task.release_lock(user)

        # if annotation created from draft - remove this draft
        if draft_id is not None:
            logger.debug(f'Remove draft {draft_id} after creating annotation {annotation.id}')
            self.delete_draft(draft_id, annotation.id)

        if self.request.data.get('ground_truth'):
            annotation.task.ensure_unique_groundtruth(annotation_id=annotation.id)

        fill_history_annotation(user, task, annotation)

        return annotation


@extend_schema(exclude=True)
class AnnotationDraftListAPI(generics.ListCreateAPIView):
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    serializer_class = AnnotationDraftSerializer
    permission_required = ViewClassPermission(
        GET=all_permissions.annotations_view,
        POST=all_permissions.annotations_create,
    )
    queryset = AnnotationDraft.objects.all()

    def _get_checked_task(self):
        """Return the parent task, enforcing task-level permissions (manual assignment scoping)."""
        task = generics.get_object_or_404(Task.objects.for_user(self.request.user), pk=self.kwargs['pk'])
        self.check_object_permissions(self.request, task)
        return task

    def filter_queryset(self, queryset):
        task = self._get_checked_task()
        return queryset.filter(task_id=task.id)

    def perform_create(self, serializer):
        task = self._get_checked_task()
        task_id = task.id
        annotation_id = self.kwargs.get('annotation_id')
        user = self.request.user
        logger.debug(f'User {user} is going to create draft for task={task_id}, annotation={annotation_id}')
        serializer.save(task_id=self.kwargs['pk'], annotation_id=annotation_id, user=self.request.user)


@extend_schema(exclude=True)
class AnnotationDraftAPI(generics.RetrieveUpdateDestroyAPIView):
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    serializer_class = AnnotationDraftSerializer
    queryset = AnnotationDraft.objects.all()
    permission_required = ViewClassPermission(
        GET=all_permissions.annotations_view,
        PUT=all_permissions.annotations_change,
        PATCH=all_permissions.annotations_change,
        DELETE=all_permissions.annotations_delete,
    )


@method_decorator(
    name='list',
    decorator=extend_schema(
        tags=['Predictions'],
        summary='List predictions',
        description='List all predictions and their IDs.',
        parameters=[
            OpenApiParameter(
                name='task',
                type=OpenApiTypes.INT,
                location='query',
                description='Filter predictions by task ID',
            ),
            OpenApiParameter(
                name='project',
                type=OpenApiTypes.INT,
                location='query',
                description='Filter predictions by project ID',
            ),
        ],
        request=None,
        responses={
            '200': OpenApiResponse(
                description='Predictions list',
                response=PredictionSerializer(many=True),
                examples=[
                    OpenApiExample(name='response', value=[prediction_response_example], media_type='application/json')
                ],
            )
        },
        extensions={
            'x-fern-sdk-group-name': 'predictions',
            'x-fern-sdk-method-name': 'list',
            'x-fern-audiences': ['public'],
        },
    ),
)
@method_decorator(
    name='create',
    decorator=extend_schema(
        tags=['Predictions'],
        summary='Create prediction',
        description='Create a prediction for a specific task.',
        request={
            'application/json': prediction_request_schema,
        },
        responses={
            '201': OpenApiResponse(
                description='Created prediction',
                response=PredictionSerializer,
                examples=[
                    OpenApiExample(name='response', value=prediction_response_example, media_type='application/json')
                ],
            )
        },
        extensions={
            'x-fern-sdk-group-name': 'predictions',
            'x-fern-sdk-method-name': 'create',
            'x-fern-audiences': ['public'],
        },
    ),
)
@method_decorator(
    name='retrieve',
    decorator=extend_schema(
        tags=['Predictions'],
        summary='Get prediction details',
        description='Get details about a specific prediction by its ID.',
        parameters=[
            OpenApiParameter(name='id', type=OpenApiTypes.INT, location='path', description='Prediction ID'),
        ],
        request=None,
        responses={
            '200': OpenApiResponse(
                description='Prediction details',
                response=PredictionSerializer,
                examples=[
                    OpenApiExample(name='response', value=prediction_response_example, media_type='application/json')
                ],
            )
        },
        extensions={
            'x-fern-sdk-group-name': 'predictions',
            'x-fern-sdk-method-name': 'get',
            'x-fern-audiences': ['public'],
        },
    ),
)
@method_decorator(
    name='update',
    decorator=extend_schema(
        tags=['Predictions'],
        summary='Put prediction',
        description='Overwrite prediction data by prediction ID.',
        parameters=[
            OpenApiParameter(name='id', type=OpenApiTypes.INT, location='path', description='Prediction ID'),
        ],
        request={
            'application/json': prediction_request_schema,
        },
        responses={
            '200': OpenApiResponse(
                description='Updated prediction',
                response=PredictionSerializer,
                examples=[
                    OpenApiExample(name='response', value=prediction_response_example, media_type='application/json')
                ],
            )
        },
        extensions={
            'x-fern-audiences': ['internal'],
        },
    ),
)
@method_decorator(
    name='partial_update',
    decorator=extend_schema(
        tags=['Predictions'],
        summary='Update prediction',
        description='Update prediction data by prediction ID.',
        parameters=[
            OpenApiParameter(name='id', type=OpenApiTypes.INT, location='path', description='Prediction ID'),
        ],
        request={
            'application/json': prediction_request_schema,
        },
        responses={
            '200': OpenApiResponse(
                description='Updated prediction',
                response=PredictionSerializer,
                examples=[
                    OpenApiExample(name='response', value=prediction_response_example, media_type='application/json')
                ],
            )
        },
        extensions={
            'x-fern-sdk-group-name': 'predictions',
            'x-fern-sdk-method-name': 'update',
            'x-fern-audiences': ['public'],
        },
    ),
)
@method_decorator(
    name='destroy',
    decorator=extend_schema(
        tags=['Predictions'],
        summary='Delete prediction',
        description='Delete a prediction by prediction ID.',
        parameters=[
            OpenApiParameter(name='id', type=OpenApiTypes.INT, location='path', description='Prediction ID'),
        ],
        request=None,
        extensions={
            'x-fern-sdk-group-name': 'predictions',
            'x-fern-sdk-method-name': 'delete',
            'x-fern-audiences': ['public'],
        },
    ),
)
class PredictionAPI(viewsets.ModelViewSet):
    serializer_class = PredictionSerializer
    permission_required = all_permissions.predictions_any
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['task', 'task__project', 'project']

    def get_queryset(self):
        return Prediction.objects.filter(project__organization=self.request.user.active_organization)


@method_decorator(name='get', decorator=extend_schema(exclude=True))
@method_decorator(
    name='post',
    decorator=extend_schema(
        tags=['Annotations'],
        summary='Convert annotation to draft',
        description='Convert annotation to draft',
        extensions={
            'x-fern-audiences': ['internal'],
        },
    ),
)
class AnnotationConvertAPI(generics.RetrieveAPIView):
    permission_required = ViewClassPermission(POST=all_permissions.annotations_change)
    queryset = Annotation.objects.all()

    def process_intermediate_state(self, annotation, draft):
        pass

    def post(self, request, *args, **kwargs):
        annotation = self.get_object()
        organization = annotation.project.organization
        project = annotation.project

        pk = annotation.pk

        with transaction.atomic():
            draft = AnnotationDraft.objects.create(
                result=annotation.result,
                lead_time=annotation.lead_time,
                task=annotation.task,
                annotation=None,
                user=request.user,
            )

            self.process_intermediate_state(annotation, draft)

            annotation.delete()

        emit_webhooks_for_instance(organization, project, WebhookAction.ANNOTATIONS_DELETED, [pk])
        data = AnnotationDraftSerializer(instance=draft).data
        return Response(status=201, data=data)

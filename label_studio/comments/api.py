"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license.
"""
import logging

from comments.serializers import CommentSerializer
from core.permissions import ViewClassPermission, all_permissions
from django.db.models import Q
from django.utils import timezone
from django.utils.decorators import method_decorator
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from .models import Comment

logger = logging.getLogger(__name__)


def _org_scoped_queryset(user):
    """Comments visible to the user: everything in the user's active organization."""
    organization = getattr(user, 'active_organization', None)
    if organization is None:
        return Comment.objects.none()
    return Comment.objects.filter(project__organization=organization).select_related(
        'created_by', 'updated_by', 'annotation', 'draft', 'task', 'project'
    )


@method_decorator(
    name='get',
    decorator=extend_schema(
        tags=['Comments'],
        summary='List comments',
        description='List comments for an annotation (or annotation draft).',
        parameters=[
            OpenApiParameter(name='annotation', type=OpenApiTypes.INT, location='query', description='Annotation ID'),
            OpenApiParameter(name='draft', type=OpenApiTypes.INT, location='query', description='Annotation draft ID'),
            OpenApiParameter(name='task', type=OpenApiTypes.INT, location='query', description='Task ID'),
            OpenApiParameter(name='project', type=OpenApiTypes.INT, location='query', description='Project ID'),
            OpenApiParameter(name='ordering', type=OpenApiTypes.STR, location='query', description='Ordering field, e.g. "-id"'),
            OpenApiParameter(
                name='expand_created_by',
                type=OpenApiTypes.BOOL,
                location='query',
                description='Return created_by as a full user object instead of an ID',
            ),
        ],
        extensions={
            'x-fern-sdk-group-name': 'comments',
            'x-fern-sdk-method-name': 'list',
            'x-fern-audiences': ['internal'],
        },
    ),
)
@method_decorator(
    name='post',
    decorator=extend_schema(
        tags=['Comments'],
        summary='Create comment',
        description='Create a comment on an annotation or annotation draft.',
        extensions={
            'x-fern-sdk-group-name': 'comments',
            'x-fern-sdk-method-name': 'create',
            'x-fern-audiences': ['internal'],
        },
    ),
)
class CommentListAPI(generics.ListCreateAPIView):
    """GET /api/comments?annotation=<id> and POST /api/comments

    The frontend CommentStore expects a plain JSON array (no pagination envelope)
    and passes ordering / expand_created_by as query params.
    """

    parser_classes = (JSONParser, FormParser, MultiPartParser)
    permission_required = ViewClassPermission(
        GET=all_permissions.annotations_view,
        POST=all_permissions.annotations_create,
    )
    serializer_class = CommentSerializer
    pagination_class = None

    ALLOWED_ORDERING = ('id', '-id', 'created_at', '-created_at', 'updated_at', '-updated_at')

    def get_queryset(self):
        queryset = _org_scoped_queryset(self.request.user)

        params = self.request.query_params
        if params.get('annotation'):
            queryset = queryset.filter(annotation_id=params['annotation'])
        if params.get('draft'):
            queryset = queryset.filter(draft_id=params['draft'])
        if params.get('task'):
            task_id = params['task']
            queryset = queryset.filter(
                Q(task_id=task_id) | Q(annotation__task_id=task_id) | Q(draft__task_id=task_id)
            )
        if params.get('project'):
            queryset = queryset.filter(project_id=params['project'])

        ordering = params.get('ordering')
        if ordering in self.ALLOWED_ORDERING:
            queryset = queryset.order_by(ordering)

        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        organization = getattr(user, 'active_organization', None)
        target = (
            serializer.validated_data.get('annotation')
            or serializer.validated_data.get('draft')
            or serializer.validated_data.get('task')
        )

        # the comment's project must belong to the user's active organization
        project = None
        if serializer.validated_data.get('annotation') is not None:
            project = serializer.validated_data['annotation'].project
        elif serializer.validated_data.get('draft') is not None and serializer.validated_data['draft'].task_id:
            project = serializer.validated_data['draft'].task.project
        elif serializer.validated_data.get('task') is not None:
            project = serializer.validated_data['task'].project

        if (
            organization is None
            or project is None
            or project.organization_id != organization.id
            or not target.has_permission(user)
        ):
            raise PermissionDenied('You do not have permission to comment on this object')

        resolved_at = timezone.now() if serializer.validated_data.get('is_resolved') else None
        serializer.save(created_by=user, updated_by=user, resolved_at=resolved_at)


@method_decorator(
    name='get',
    decorator=extend_schema(
        tags=['Comments'],
        summary='Get comment',
        description='Get a specific comment by ID.',
        extensions={
            'x-fern-sdk-group-name': 'comments',
            'x-fern-sdk-method-name': 'get',
            'x-fern-audiences': ['internal'],
        },
    ),
)
@method_decorator(
    name='patch',
    decorator=extend_schema(
        tags=['Comments'],
        summary='Update comment',
        description='Update a comment (edit text, resolve/unresolve, set region link or classifications).',
        extensions={
            'x-fern-sdk-group-name': 'comments',
            'x-fern-sdk-method-name': 'update',
            'x-fern-audiences': ['internal'],
        },
    ),
)
@method_decorator(
    name='delete',
    decorator=extend_schema(
        tags=['Comments'],
        summary='Delete comment',
        description='Delete a comment. Only the author or an organization administrator can delete a comment.',
        extensions={
            'x-fern-sdk-group-name': 'comments',
            'x-fern-sdk-method-name': 'delete',
            'x-fern-audiences': ['internal'],
        },
    ),
)
@method_decorator(name='put', decorator=extend_schema(exclude=True))
class CommentAPI(generics.RetrieveUpdateDestroyAPIView):
    """GET|PATCH|DELETE /api/comments/<id>"""

    parser_classes = (JSONParser, FormParser, MultiPartParser)
    permission_required = ViewClassPermission(
        GET=all_permissions.annotations_view,
        PUT=all_permissions.annotations_change,
        PATCH=all_permissions.annotations_change,
        DELETE=all_permissions.annotations_delete,
    )
    serializer_class = CommentSerializer

    def get_queryset(self):
        return _org_scoped_queryset(self.request.user)

    def check_write_permission(self, request, comment):
        """Only the comment author or an organization admin may modify a comment."""
        user = request.user
        if comment.created_by_id == user.id:
            return
        project = comment.get_project()
        organization_id = project.organization_id if project is not None else None
        if organization_id and user.is_organization_admin(organization_id):
            return
        raise PermissionDenied('Only the comment author or an organization administrator can modify this comment')

    def update(self, request, *args, **kwargs):
        comment = self.get_object()
        self.check_write_permission(request, comment)
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        comment = serializer.instance

        # keep resolved_at in sync with is_resolved transitions
        is_resolved = serializer.validated_data.get('is_resolved', comment.is_resolved)
        resolved_at = comment.resolved_at
        if is_resolved != comment.is_resolved:
            resolved_at = timezone.now() if is_resolved else None

        serializer.save(updated_by=self.request.user, resolved_at=resolved_at)

    def destroy(self, request, *args, **kwargs):
        comment = self.get_object()
        self.check_write_permission(request, comment)
        return super().destroy(request, *args, **kwargs)

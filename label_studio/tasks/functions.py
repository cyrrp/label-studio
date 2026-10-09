import json
import logging
import os
import shutil
import sys

from core.models import AsyncMigrationStatus
from core.redis import start_job_async_or_sync
from core.utils.common import batch, batched_iterator
from core.utils.iterators import iterate_queryset
from data_export.mixins import ExportMixin
from data_export.models import DataExport
from data_export.serializers import ExportDataSerializer
from data_manager.managers import TaskQuerySet
from django.conf import settings
from django.db.models import Count, F, Q
from organizations.models import Organization
from projects.models import Project
from tasks.models import Annotation, Prediction, Task

logger = logging.getLogger(__name__)


def calculate_stats_all_orgs(from_scratch, redis, migration_name='0018_manual_migrate_counters'):
    logger = logging.getLogger(__name__)
    # Don't load full Organization objects bc some columns (contact_info, verify_ssl_certs)
    # aren't created until after a migration calls this code
    organization_ids = Organization.objects.order_by('-id').values_list('id', flat=True)

    for org_id in organization_ids:
        logger.debug(f'Start recalculating stats for Organization {org_id}')

        # start async calculation job on redis
        start_job_async_or_sync(
            redis_job_for_calculation,
            org_id,
            from_scratch,
            redis=redis,
            queue_name='critical',
            job_timeout=3600 * 24,  # 24 hours for one organization
            migration_name=migration_name,
        )

        logger.debug(f'Organization {org_id} stats were recalculated')

    logger.debug('All organizations were recalculated')


def redis_job_for_calculation(org_id, from_scratch, migration_name='0018_manual_migrate_counters'):
    """
    Recalculate counters for projects list
    :param org_id: ID of organization to recalculate
    :param from_scratch: Start calculation from scratch or skip calculated tasks
    """
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    project_dicts = (
        Project.objects.filter(organization_id=org_id)
        .order_by('-updated_at')
        .values(
            'id',
            'updated_at',
            'title',
        )
    )
    for project_dict in project_dicts:
        migration = AsyncMigrationStatus.objects.create(
            project_id=project_dict['id'],
            name=migration_name,
            status=AsyncMigrationStatus.STATUS_STARTED,
        )
        project_tasks = Task.objects.filter(project_id=project_dict['id'])
        logger.debug(
            f'Start processing stats project <{project_dict["title"]}> ({project_dict["id"]}) '
            f'with task count {project_tasks.count()} and updated_at {project_dict["updated_at"]}'
        )

        task_count = update_tasks_counters(project_tasks, from_scratch=from_scratch)

        migration.status = AsyncMigrationStatus.STATUS_FINISHED
        migration.meta = {'tasks_processed': task_count, 'total_project_tasks': project_tasks.count()}
        migration.save()
        logger.debug(
            f'End processing counters for project <{project_dict["title"]}> ({project_dict["id"]}), '
            f'processed {str(task_count)} tasks'
        )


def export_project(project_id, export_format, path, serializer_context=None):
    logger = logging.getLogger(__name__)

    project = Project.objects.get(id=project_id)

    export_format = export_format.upper()
    supported_formats = [s['name'] for s in DataExport.get_export_formats(project)]
    assert export_format in supported_formats, f'Export format is not supported, please use {supported_formats}'

    task_ids = (
        Task.objects.filter(project=project).select_related('project').prefetch_related('annotations', 'predictions')
    )

    logger.debug(f'Start exporting project <{project.title}> ({project.id}) with task count {task_ids.count()}.')

    # serializer context
    if isinstance(serializer_context, str):
        serializer_context = json.loads(serializer_context)
    serializer_options = ExportMixin._get_export_serializer_option(serializer_context)

    # export cycle
    tasks = []
    for _task_ids in batch(task_ids, 1000):
        tasks += ExportDataSerializer(_task_ids, many=True, **serializer_options).data

    # convert to output format
    export_file, _, filename = DataExport.generate_export_file(
        project, tasks, export_format, settings.CONVERTER_DOWNLOAD_RESOURCES, {}
    )

    # write to file
    filepath = os.path.join(path, filename) if os.path.isdir(path) else path
    with open(filepath, 'wb') as file:
        shutil.copyfileobj(export_file, file)
    export_file.close()

    logger.debug(f'End exporting project <{project.title}> ({project.id}) in {export_format} format.')

    return filepath


def _fill_annotations_project(project_id):
    Annotation.objects.filter(task__project_id=project_id).update(project_id=project_id)


def fill_annotations_project():
    logger.info('Start filling project field for Annotation model')

    project_ids = Project.objects.all().values_list('id', flat=True)
    for project_id in project_ids:
        start_job_async_or_sync(_fill_annotations_project, project_id)

    logger.info('Finished filling project field for Annotation model')


def _fill_predictions_project(migration_name='0043_auto_20230825'):
    project_ids = Project.objects.all().values_list('id', flat=True)
    for project_id in project_ids:
        migration = AsyncMigrationStatus.objects.create(
            project_id=project_id,
            name=migration_name,
            status=AsyncMigrationStatus.STATUS_STARTED,
        )

        updated_count = Prediction.objects.filter(task__project_id=project_id).update(project_id=project_id)

        migration.status = AsyncMigrationStatus.STATUS_FINISHED
        migration.meta = {
            'predictions_processed': updated_count,
            'total_project_predictions': Prediction.objects.filter(project_id=project_id).count(),
        }
        migration.save()


def fill_predictions_project(migration_name):
    logger.info('Start filling project field for Prediction model')
    start_job_async_or_sync(_fill_predictions_project, migration_name=migration_name)
    logger.info('Finished filling project field for Prediction model')


def update_tasks_counters(queryset, from_scratch=True):
    """
    Update tasks counters for the passed queryset of Tasks
    :param queryset: Tasks to update queryset
    :param from_scratch: Skip calculated tasks
    :return: Count of updated tasks
    """
    total_annotations = Count('annotations', distinct=True, filter=Q(annotations__was_cancelled=False))
    cancelled_annotations = Count('annotations', distinct=True, filter=Q(annotations__was_cancelled=True))
    total_predictions = Count('predictions', distinct=True)
    # construct QuerySet in case of list of Tasks
    if isinstance(queryset, list) and len(queryset) > 0 and isinstance(queryset[0], Task):
        queryset = Task.objects.filter(id__in=[task.id for task in queryset])
    # construct QuerySet in case annotated queryset
    if isinstance(queryset, TaskQuerySet) and queryset.exists() and isinstance(queryset[0], int):
        queryset = Task.objects.filter(id__in=queryset)

    if not from_scratch:
        queryset = queryset.exclude(
            Q(total_annotations__gt=0) | Q(cancelled_annotations__gt=0) | Q(total_predictions__gt=0)
        )

    # filter our tasks with 0 annotations and 0 predictions and update them with 0
    # order_by('id') ensures consistent row locking order to prevent deadlocks
    queryset.filter(annotations__isnull=True, predictions__isnull=True).order_by('id').update(
        total_annotations=0, cancelled_annotations=0, total_predictions=0
    )

    # filter our tasks with 0 annotations and 0 predictions
    queryset = queryset.filter(Q(annotations__isnull=False) | Q(predictions__isnull=False))
    queryset = queryset.annotate(
        new_total_annotations=total_annotations,
        new_cancelled_annotations=cancelled_annotations,
        new_total_predictions=total_predictions,
    )

    updated_count = 0

    tasks_iterator = iterate_queryset(
        queryset.only('id', 'total_annotations', 'cancelled_annotations', 'total_predictions'),
        chunk_size=settings.BATCH_SIZE,
    )

    for _batch in batched_iterator(tasks_iterator, settings.BATCH_SIZE):
        batch_list = []
        for task in _batch:
            task.total_annotations = task.new_total_annotations
            task.cancelled_annotations = task.new_cancelled_annotations
            task.total_predictions = task.new_total_predictions
            batch_list.append(task)

        if batch_list:
            Task.objects.bulk_update(
                batch_list,
                ['total_annotations', 'cancelled_annotations', 'total_predictions'],
                batch_size=settings.BATCH_SIZE,
            )
            updated_count += len(batch_list)

    return updated_count


def bulk_update_is_labeled_by_overlap(tasks_ids, project):
    if not tasks_ids:
        return

    batch_size = settings.BATCH_SIZE

    # Use distinct annotator count for overlap comparison
    for i in range(0, len(tasks_ids), batch_size):
        batch_ids = tasks_ids[i : i + batch_size]

        # Annotate with distinct annotator count
        if project.skip_queue == project.SkipQueue.IGNORE_SKIPPED:
            annotator_count_expr = Count('annotations__completed_by', distinct=True)
        else:
            annotator_count_expr = Count(
                'annotations__completed_by',
                distinct=True,
                filter=Q(annotations__was_cancelled=False),
            )

        tasks_qs = Task.objects.filter(id__in=batch_ids, project=project).annotate(
            annotator_count=annotator_count_expr
        )

        # Get IDs of tasks that meet the overlap requirement
        finished_task_ids = list(tasks_qs.filter(annotator_count__gte=F('overlap')).values_list('id', flat=True))

        # Update is_labeled based on annotator count
        Task.objects.filter(id__in=finished_task_ids, project=project).update(is_labeled=True)
        Task.objects.filter(id__in=batch_ids, project=project).exclude(id__in=finished_task_ids).update(
            is_labeled=False
        )


# ---------------------------------------------------------------------------
# Review workflow: Data Manager annotation helpers
#
# Registered into settings.DATA_MANAGER_ANNOTATIONS_MAP from TasksConfig.ready()
# via data_manager.managers.update_annotation_map so that community review
# columns (reviewed / reviewers / reviews_accepted / reviews_rejected /
# reviewed_at) work without touching the data_manager app.
# ---------------------------------------------------------------------------


def annotate_reviewed(queryset):
    """`reviewed` column: True when the task has at least one non-rejected review."""
    from django.db.models import Exists, OuterRef
    from tasks.choices import ReviewResult
    from tasks.models import AnnotationReview

    reviewed = Exists(
        AnnotationReview.objects.filter(
            annotation__task=OuterRef('pk'),
            result__in=[ReviewResult.ACCEPTED, ReviewResult.FIXED_AND_ACCEPTED],
        )
    )
    return queryset.annotate(reviewed=reviewed)


def _reviewers_string_agg(expression):
    """Comma-joined list of user ids for both SQLite and Postgres."""
    from django.conf import settings as dj_settings
    from django.db.models import Aggregate, Value
    from django.db.models.fields import CharField, TextField
    from django.db.models.functions import Cast, Coalesce

    if dj_settings.DJANGO_DB == dj_settings.DJANGO_DB_SQLITE:
        # data_manager.managers.GroupConcat doesn't support distinct=True,
        # so use a local aggregate that does
        class _GroupConcatDistinct(Aggregate):
            function = 'GROUP_CONCAT'
            template = '%(function)s(%(distinct)s%(expressions)s)'
            allow_distinct = True

        return Coalesce(
            _GroupConcatDistinct(Cast(expression, output_field=TextField()), distinct=True),
            Value(''),
            output_field=CharField(),
        )

    from django.contrib.postgres.aggregates import StringAgg

    return Coalesce(
        StringAgg(Cast(expression, output_field=TextField()), delimiter=',', distinct=True),
        Value(''),
        output_field=CharField(),
    )


def annotate_reviewers(queryset):
    """`reviewers` column: users who reviewed the task + users assigned as reviewers."""
    from django.db.models import Case, F, Value, When
    from django.db.models.fields import CharField
    from django.db.models.functions import Concat
    from tasks.models import TaskAssignment

    reviewed_by = _reviewers_string_agg('annotations__reviews__created_by')
    assigned_reviewers = _reviewers_string_agg(
        Case(
            When(assignments__role=TaskAssignment.Role.REVIEWER, then=F('assignments__user')),
            output_field=CharField(),
        )
    )
    queryset = queryset.annotate(_reviewed_by=reviewed_by, _assigned_reviewers=assigned_reviewers)
    return queryset.annotate(
        reviewers=Case(
            When(_reviewed_by='', then=F('_assigned_reviewers')),
            When(_assigned_reviewers='', then=F('_reviewed_by')),
            default=Concat(F('_reviewed_by'), Value(','), F('_assigned_reviewers')),
            output_field=CharField(),
        )
    )


def annotate_reviews_rejected(queryset):
    """`reviews_rejected` column: number of rejected reviews on the task."""
    from django.db.models import Count, Q
    from tasks.choices import ReviewResult

    return queryset.annotate(
        reviews_rejected=Count(
            'annotations__reviews', filter=Q(annotations__reviews__result=ReviewResult.REJECTED), distinct=True
        )
    )


def annotate_reviews_accepted(queryset):
    """`reviews_accepted` column: accepted + fixed_and_accepted reviews on the task."""
    from django.db.models import Count, Q
    from tasks.choices import ReviewResult

    return queryset.annotate(
        reviews_accepted=Count(
            'annotations__reviews',
            filter=Q(
                annotations__reviews__result__in=[ReviewResult.ACCEPTED, ReviewResult.FIXED_AND_ACCEPTED]
            ),
            distinct=True,
        )
    )


def annotate_reviewed_at(queryset):
    """`reviewed_at`: last time a review was written on the task."""
    from django.db.models import Max

    return queryset.annotate(reviewed_at=Max('annotations__reviews__updated_at'))


def _assigned_users_for_role(queryset, role, annotation_name):
    """Comma-joined user ids holding a TaskAssignment of the given role on the task."""
    from django.db.models import Case, F, When
    from django.db.models.fields import CharField

    return queryset.annotate(
        **{
            annotation_name: _reviewers_string_agg(
                Case(When(assignments__role=role, then=F('assignments__user')), output_field=CharField())
            )
        }
    )


def annotate_assigned_annotators(queryset):
    """`assigned_annotators` column: users with an ANNOTATOR assignment on the task."""
    from tasks.models import TaskAssignment

    return _assigned_users_for_role(queryset, TaskAssignment.Role.ANNOTATOR, 'assigned_annotators')


def annotate_assigned_reviewers(queryset):
    """`assigned_reviewers` column: users with a REVIEWER assignment on the task."""
    from tasks.models import TaskAssignment

    return _assigned_users_for_role(queryset, TaskAssignment.Role.REVIEWER, 'assigned_reviewers')


ASSIGNMENT_ANNOTATIONS_MAP = {
    'assigned_annotators': annotate_assigned_annotators,
    'assigned_reviewers': annotate_assigned_reviewers,
}


REVIEW_ANNOTATIONS_MAP = {
    'reviewed': annotate_reviewed,
    'reviewers': annotate_reviewers,
    'reviews_rejected': annotate_reviews_rejected,
    'reviews_accepted': annotate_reviews_accepted,
    'reviewed_at': annotate_reviewed_at,
}


def register_review_annotation_map():
    """Register review and assignment columns into settings.DATA_MANAGER_ANNOTATIONS_MAP.

    Called from TasksConfig.ready(); kept out of data_manager/* on purpose
    (community edition can't edit that app).
    """
    from data_manager.managers import update_annotation_map

    update_annotation_map(REVIEW_ANNOTATIONS_MAP)
    update_annotation_map(ASSIGNMENT_ANNOTATIONS_MAP)


ASSIGNMENT_FILTER_ROLES = {
    'assigned_annotators': 'AN',
    'assigned_reviewers': 'RE',
}


def review_custom_filter_expressions(_filter, field_name, project, request=None, is_child_filter=False):
    """Data Manager custom filter hook for review and assignment columns.

    data_manager.managers.apply_filters() resolves
    settings.DATA_MANAGER_CUSTOM_FILTER_EXPRESSIONS via load_func() on every
    call; TasksConfig.ready() replaces data_manager.functions.custom_filter_expressions
    (a no-op stub in community) with this function, so it must delegate to the
    default behavior by returning None for fields it doesn't handle.
    """
    from django.db.models import Exists, OuterRef, Q
    from tasks.models import AnnotationReview, TaskAssignment

    operator = getattr(_filter, 'operator', '')

    if field_name in ASSIGNMENT_FILTER_ROLES:
        role = TaskAssignment.Role(ASSIGNMENT_FILTER_ROLES[field_name])
        if operator in ('contains', 'not_contains'):
            user_id = int(_filter.value)
            q = Q(
                Exists(TaskAssignment.objects.filter(task=OuterRef('pk'), user_id=user_id, role=role))
            )
            return q if operator == 'contains' else ~q
        if operator == 'empty':
            from core.utils.params import cast_bool_from_str

            value = cast_bool_from_str(_filter.value)
            q = Q(Exists(TaskAssignment.objects.filter(task=OuterRef('pk'), role=role)))
            return ~q if value else q
        return None

    if field_name != 'reviewers':
        return None

    if operator in ('contains', 'not_contains'):
        user_id = int(_filter.value)
        reviewed = Exists(AnnotationReview.objects.filter(annotation__task=OuterRef('pk'), created_by_id=user_id))
        assigned = Exists(
            TaskAssignment.objects.filter(task=OuterRef('pk'), user_id=user_id, role=TaskAssignment.Role.REVIEWER)
        )
        q = Q(reviewed) | Q(assigned)
        return q if operator == 'contains' else ~q
    if operator == 'empty':
        from core.utils.params import cast_bool_from_str

        value = cast_bool_from_str(_filter.value)
        reviewed = Exists(AnnotationReview.objects.filter(annotation__task=OuterRef('pk')))
        assigned = Exists(TaskAssignment.objects.filter(task=OuterRef('pk'), role=TaskAssignment.Role.REVIEWER))
        q = Q(reviewed) | Q(assigned)
        return ~q if value else q
    return None

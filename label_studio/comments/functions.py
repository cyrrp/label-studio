"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license.
"""
import logging

from django.db.models import Count, Max, Q

logger = logging.getLogger(__name__)


def update_task_comment_counters(task):
    """Recompute Task.comment_count / unresolved_comment_count /
    last_comment_updated_at / comment_authors for the given task.

    Uses a queryset update instead of task.save() to avoid triggering
    task save logic (FSM, is_labeled, updated_at) from comment signals.
    """
    from comments.models import Comment
    from tasks.models import Task

    if task is None:
        return

    # the task itself might already be gone (cascade delete)
    task_id = task.pk if hasattr(task, 'pk') else task
    if not Task.objects.filter(id=task_id).exists():
        return

    comments = Comment.objects.filter(Q(task_id=task_id) | Q(annotation__task_id=task_id))
    stats = comments.aggregate(
        total=Count('id'),
        unresolved=Count('id', filter=Q(is_resolved=False)),
        last_updated=Max('updated_at'),
    )

    Task.objects.filter(id=task_id).update(
        comment_count=stats['total'],
        unresolved_comment_count=stats['unresolved'],
        last_comment_updated_at=stats['last_updated'],
    )

    author_ids = list(
        comments.exclude(created_by_id__isnull=True)
        .values_list('created_by_id', flat=True)
        .distinct()
    )
    try:
        Task.objects.get(id=task_id).comment_authors.set(author_ids)
    except Exception as e:
        logger.warning(f'Failed to update comment_authors for task {task_id}: {e}')


def on_comment_saved(sender, instance, **kwargs):
    update_task_comment_counters(instance.get_task())


def on_comment_deleted(sender, instance, **kwargs):
    update_task_comment_counters(instance.get_task())

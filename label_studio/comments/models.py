"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license.
"""
import logging

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


class Comment(models.Model):
    """Comment on an annotation (or annotation draft).

    Mirrors the LSE comments contract expected by the frontend CommentStore:
    comments are attached to an annotation (or a draft before the annotation
    exists), keep denormalized task/project FKs for filtering and task-level
    counters, and support resolve / region-link / classification payloads.
    """

    text = models.TextField(_('text'), help_text='Comment body')

    annotation = models.ForeignKey(
        'tasks.Annotation',
        on_delete=models.CASCADE,
        related_name='comments',
        null=True,
        blank=True,
        help_text='Annotation this comment belongs to',
    )
    draft = models.ForeignKey(
        'tasks.AnnotationDraft',
        on_delete=models.CASCADE,
        related_name='comments',
        null=True,
        blank=True,
        help_text='Annotation draft this comment belongs to (used before the annotation is created)',
    )

    # denormalized relations for filtering and task counters
    task = models.ForeignKey(
        'tasks.Task',
        on_delete=models.CASCADE,
        related_name='comments',
        null=True,
        blank=True,
        help_text='Task this comment belongs to (derived from annotation or draft)',
    )
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='comments',
        null=True,
        blank=True,
        help_text='Project this comment belongs to (derived from annotation or draft)',
    )

    is_resolved = models.BooleanField(
        _('is resolved'), default=False, help_text='Whether the comment thread was resolved'
    )
    resolved_at = models.DateTimeField(
        _('resolved at'), null=True, default=None, help_text='When the comment was resolved'
    )

    # e.g. {"region_id": ..., "control_name": ...} - links a comment to a region/result
    region_ref = models.JSONField(
        _('region ref'), null=True, default=None, help_text='Reference to the region/result this comment is anchored to'
    )
    classifications = models.JSONField(
        _('classifications'), null=True, default=None, help_text='Comment classifications payload'
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='comments',
        null=True,
        help_text='User who wrote this comment',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='updated_comments',
        null=True,
        help_text='Last user who updated this comment',
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True, help_text='Creation time')
    updated_at = models.DateTimeField(_('updated at'), auto_now=True, help_text='Last update time')

    class Meta:
        db_table = 'comment'
        ordering = ['created_at']

    def get_task(self):
        """Resolve the task this comment belongs to (denormalized or via annotation/draft).

        Returns None instead of raising when a related target was already removed
        (e.g. while cascades run post_delete for this comment).
        """
        from tasks.models import Annotation, AnnotationDraft, Task

        if self.task_id:
            return Task.objects.filter(id=self.task_id).first()
        if self.annotation_id:
            annotation = Annotation.objects.filter(id=self.annotation_id).first()
            return annotation.task if annotation is not None and annotation.task_id else None
        if self.draft_id:
            draft = AnnotationDraft.objects.filter(id=self.draft_id).first()
            return draft.task if draft is not None and draft.task_id else None
        return None

    def get_project(self):
        """Resolve the project this comment belongs to (denormalized or via annotation/draft/task)."""
        from projects.models import Project
        from tasks.models import Annotation

        if self.project_id:
            return Project.objects.filter(id=self.project_id).first()
        if self.annotation_id:
            annotation = Annotation.objects.filter(id=self.annotation_id).first()
            return annotation.project if annotation is not None else None
        task = self.get_task()
        if task is not None:
            return task.project
        return None

    def has_permission(self, user: 'User') -> bool:  # noqa: F821
        project = self.get_project()
        if project is None:
            return False
        user.project = project  # link for activity log
        return project.has_permission(user)

    def save(self, *args, **kwargs):
        # keep denormalized relations in sync with the comment target
        try:
            self._sync_denormalized_fields()
        except ObjectDoesNotExist:
            logger.warning(f'Comment {self.pk}: denormalized task/project sync skipped - target not found')
        super().save(*args, **kwargs)

    def _sync_denormalized_fields(self):
        if self.annotation_id:
            self.task_id = self.annotation.task_id
            self.project_id = self.annotation.project_id
        elif self.draft_id:
            self.task_id = self.draft.task_id
            if self.draft.task_id:
                self.project_id = self.draft.task.project_id
        elif self.task_id and not self.project_id:
            self.project_id = self.task.project_id

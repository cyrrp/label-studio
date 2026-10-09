"""Comments Django App Configuration"""

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class CommentsConfig(AppConfig):
    name = 'comments'
    verbose_name = 'Label Studio Comments'

    def ready(self):
        """
        Connect signal receivers that keep Task comment counters
        (comment_count / unresolved_comment_count / comment_authors /
        last_comment_updated_at) in sync with the Comment table.
        """
        from django.db.models.signals import post_delete, post_save

        from . import models as comment_models  # noqa: F401
        from .functions import on_comment_deleted, on_comment_saved

        post_save.connect(
            on_comment_saved,
            sender=comment_models.Comment,
            dispatch_uid='comments.on_comment_saved',
        )
        post_delete.connect(
            on_comment_deleted,
            sender=comment_models.Comment,
            dispatch_uid='comments.on_comment_deleted',
        )

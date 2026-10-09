"""Tasks Django App Configuration"""

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class TasksConfig(AppConfig):
    name = 'tasks'

    def ready(self):
        """
        Tasks app initialization.

        Note: FSM transitions are now registered centrally in fsm/apps.py.
        Do NOT import transitions here to avoid duplicate registration.
        """
        # Community review workflow: register review columns (reviewed, reviewers,
        # reviews_*, reviewed_at) into the Data Manager annotation map and provide
        # exact-match filtering for the `reviewers` column through the
        # custom_filter_expressions hook. Both hooks live in data_manager but are
        # extension points designed for this, so no data_manager code is touched.
        from tasks.functions import register_review_annotation_map, review_custom_filter_expressions

        register_review_annotation_map()

        try:
            import data_manager.functions as dm_functions

            _original_custom_filter = dm_functions.custom_filter_expressions

            def _custom_filter_expressions(_filter, field_name, project, **kwargs):
                expr = review_custom_filter_expressions(_filter, field_name, project, **kwargs)
                if expr is not None:
                    return expr
                if callable(_original_custom_filter):
                    return _original_custom_filter(_filter, field_name, project, **kwargs)
                return None

            dm_functions.custom_filter_expressions = _custom_filter_expressions
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning('Failed to install review filter hook: %s', exc)

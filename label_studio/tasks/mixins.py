def _is_project_annotator(user, project) -> bool:
    """Safely check whether the user is a project annotator.

    `is_project_annotator` is provided by the User model (role-based, see users.mixins.UserMixin);
    it may be missing on AnonymousUser or SimpleLazyObject wrappers, so use getattr.
    """
    checker = getattr(user, 'is_project_annotator', None)
    if project is None or checker is None:
        return False
    try:
        return bool(checker(project))
    except Exception:
        return False


class TaskMixin:
    def has_permission(self, user: 'User') -> bool:  # noqa: F821
        """Called by Task#has_permission.

        Annotators (organization role 'AN') may only access tasks that are
        manually assigned to them; all other roles keep unrestricted access.
        """
        if self.project_id and _is_project_annotator(user, self.project):
            return self.assignments.filter(user=user).exists()
        return True

    def _get_is_labeled_value(self) -> bool:
        n = self.completed_annotations.values('completed_by').distinct().count()
        return n >= self.overlap

    def update_is_labeled(self, *args, **kwargs) -> None:
        self.is_labeled = self._get_is_labeled_value()

    @classmethod
    def post_process_bulk_update_stats(cls, tasks) -> None:
        pass

    def before_delete_actions(self):
        """
        Actions to execute before task deletion
        """
        pass

    @staticmethod
    def after_bulk_delete_actions(tasks_ids, project):
        """
        Actions to execute after bulk task deletion
        """
        pass

    def can_be_skipped(self) -> bool:
        return True


class AnnotationMixin:
    def has_permission(self, user: 'User') -> bool:  # noqa: F821
        """Called by Annotation#has_permission.

        Users may always access their own annotations. Annotators may only access
        annotations on tasks assigned to them; other roles are unrestricted.
        """
        user_id = getattr(user, 'id', None)
        if self.completed_by_id is not None and self.completed_by_id == user_id:
            return True

        task = self.task
        if task is not None and _is_project_annotator(user, task.project):
            return task.assignments.filter(user=user).exists()
        return True

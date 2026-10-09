"""Tests for real task assignment (TaskAssignment model + enforcement).

The role machinery (`user.is_annotator`, `user.is_project_annotator`) is provided
by users.mixins; tests patch `User.is_project_annotator` directly so they exercise
only the assignment logic written against that contract.
"""
from types import SimpleNamespace
from unittest.mock import patch

from data_manager.actions.assignment import (
    assign_annotators,
    assign_reviewers,
    delete_annotators,
    delete_reviewers,
)
from data_manager.prepare_params import Filters, PrepareParams
from django.http import HttpRequest
from django.test import TestCase
from organizations.tests.factories import OrganizationFactory
from projects.functions.next_task import get_next_task, scope_tasks_to_assignments
from projects.tests.factories import ProjectFactory
from tasks.models import Annotation, Task, TaskAssignment
from tasks.tests.factories import AnnotationFactory, TaskFactory
from users.models import User
from users.tests.factories import UserFactory


def as_annotator(user):
    """Patch so that only `user` is treated as a project annotator."""
    return patch.object(User, 'is_project_annotator', lambda self, project: self.pk == user.pk)


def make_request(user, data=None):
    request = HttpRequest()
    request.user = user
    request.data = data or {}
    return request


class TestTaskAssignmentPermissions(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory()
        cls.project = ProjectFactory(organization=cls.organization)
        cls.owner = cls.organization.created_by
        cls.annotator = UserFactory(active_organization=cls.organization)
        cls.task1 = TaskFactory(project=cls.project)
        cls.task2 = TaskFactory(project=cls.project)

    def test_assign_to_is_idempotent(self):
        a1 = TaskAssignment.assign_to(self.task1, self.annotator, assigned_by=self.owner)
        a2 = TaskAssignment.assign_to(self.task1, self.annotator)
        assert a1.pk == a2.pk
        assert TaskAssignment.objects.count() == 1
        assert a1.role == TaskAssignment.Role.ANNOTATOR
        assert a1.assigned_by == self.owner

    def test_task_has_permission_scoped_for_annotator(self):
        with as_annotator(self.annotator):
            assert self.task1.has_permission(self.annotator) is False
            TaskAssignment.assign_to(self.task1, self.annotator)
            assert self.task1.has_permission(self.annotator) is True
            # still no access to the unassigned task
            assert self.task2.has_permission(self.annotator) is False

    def test_task_has_permission_unaffected_for_other_roles(self):
        with as_annotator(self.annotator):
            assert self.task1.has_permission(self.owner) is True
            assert self.task2.has_permission(self.owner) is True

    def test_annotation_has_permission(self):
        own = AnnotationFactory(task=self.task2, completed_by=self.annotator)
        alien = AnnotationFactory(task=self.task1, completed_by=self.owner)

        with as_annotator(self.annotator):
            # annotator's own annotation is always reachable
            assert own.has_permission(self.annotator) is True
            # alien annotation on unassigned task is denied
            assert alien.has_permission(self.annotator) is False
            # ... until the task gets assigned
            TaskAssignment.assign_to(self.task1, self.annotator)
            assert alien.has_permission(self.annotator) is True

    def test_scope_tasks_to_assignments(self):
        tasks = Task.objects.filter(project=self.project)
        with as_annotator(self.annotator):
            scoped, flag = scope_tasks_to_assignments(self.annotator, self.project, tasks)
            assert flag is True
            assert scoped.count() == 0
            TaskAssignment.assign_to(self.task1, self.annotator)
            scoped, flag = scope_tasks_to_assignments(self.annotator, self.project, tasks)
            assert list(scoped.values_list('id', flat=True)) == [self.task1.id]

            # other roles are not scoped
            scoped, flag = scope_tasks_to_assignments(self.owner, self.project, tasks)
            assert flag is False
            assert scoped.count() == 2

    def test_next_task_serves_only_assigned(self):
        TaskAssignment.assign_to(self.task2, self.annotator)
        tasks = Task.objects.filter(project=self.project).order_by('id')
        with as_annotator(self.annotator):
            scoped, flag = scope_tasks_to_assignments(self.annotator, self.project, tasks)
            next_task, queue_info = get_next_task(
                self.annotator, scoped, self.project, dm_queue=None, assigned_flag=flag
            )
            assert next_task is not None
            assert next_task.id == self.task2.id
            assert 'Manually assigned queue' in queue_info

    def test_prepared_queryset_scoped_for_annotator(self):
        request = make_request(self.annotator)
        prepare_params = PrepareParams(project=self.project.id, request=request)
        with as_annotator(self.annotator):
            qs = Task.prepared.only_filtered(prepare_params=prepare_params)
            assert qs.count() == 0
            TaskAssignment.assign_to(self.task1, self.annotator)
            qs = Task.prepared.only_filtered(prepare_params=prepare_params)
            assert list(qs.values_list('id', flat=True)) == [self.task1.id]

        # owner sees everything
        request.user = self.owner
        prepare_params.request = request
        with as_annotator(self.annotator):
            qs = Task.prepared.only_filtered(prepare_params=prepare_params)
            assert qs.count() == 2


class TestAssignmentActions(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory()
        cls.project = ProjectFactory(organization=cls.organization)
        cls.owner = cls.organization.created_by
        cls.annotator = UserFactory(active_organization=cls.organization)
        cls.reviewer = UserFactory(active_organization=cls.organization)
        cls.task1 = TaskFactory(project=cls.project)
        cls.task2 = TaskFactory(project=cls.project)
        cls.tasks = Task.objects.filter(project=cls.project)

    def test_assign_annotators_action(self):
        request = make_request(self.owner, {'annotators': [str(self.annotator.id)]})
        result = assign_annotators(self.project, self.tasks, request=request)
        assert result['processed_items'] == 2
        assert TaskAssignment.objects.filter(
            role=TaskAssignment.Role.ANNOTATOR, user=self.annotator
        ).count() == 2

        # re-running doesn't duplicate rows
        result = assign_annotators(self.project, self.tasks, request=request)
        assert '0 new assignments' in result['detail']
        assert TaskAssignment.objects.count() == 2

    def test_assign_accepts_scalar_and_ignores_non_members(self):
        outsider = UserFactory()  # different organization
        request = make_request(self.owner, {'annotators': [str(self.annotator.id), str(outsider.id)]})
        assign_annotators(self.project, self.tasks, request=request)
        assert TaskAssignment.objects.filter(user=self.annotator).exists()
        assert not TaskAssignment.objects.filter(user=outsider).exists()

        # a single scalar value works too, an empty selection is a no-op
        TaskAssignment.objects.all().delete()
        request = make_request(self.owner, {'annotators': str(self.annotator.id)})
        assign_annotators(self.project, Task.objects.filter(pk=self.task1.pk), request=request)
        assert TaskAssignment.objects.filter(user=self.annotator, task=self.task1).count() == 1

        request = make_request(self.owner, {'annotators': ''})
        assert assign_annotators(self.project, self.tasks, request=request)['processed_items'] == 0

    def test_delete_annotators_action(self):
        request = make_request(self.owner, {'annotators': [self.annotator.id, self.reviewer.id]})
        assign_annotators(self.project, self.tasks, request=request)
        assert TaskAssignment.objects.count() == 4

        # unassign only one user
        request = make_request(self.owner, {'annotators': [self.reviewer.id]})
        result = delete_annotators(self.project, self.tasks, request=request)
        assert result['processed_items'] == 2
        assert TaskAssignment.objects.filter(user=self.annotator).count() == 2
        assert not TaskAssignment.objects.filter(user=self.reviewer).exists()

        # empty selection removes all
        request = make_request(self.owner, {'annotators': ''})
        delete_annotators(self.project, self.tasks, request=request)
        assert TaskAssignment.objects.filter(role=TaskAssignment.Role.ANNOTATOR).count() == 0

    def test_reviewer_actions_use_re_role(self):
        request = make_request(self.owner, {'reviewers': [self.reviewer.id]})
        assign_reviewers(self.project, self.tasks, request=request)
        assert TaskAssignment.objects.filter(role=TaskAssignment.Role.REVIEWER).count() == 2

        # annotator deletions don't touch reviewer rows
        request = make_request(self.owner, {'annotators': ''})
        delete_annotators(self.project, self.tasks, request=request)
        assert TaskAssignment.objects.filter(role=TaskAssignment.Role.REVIEWER).count() == 2

        request = make_request(self.owner, {'reviewers': ''})
        delete_reviewers(self.project, self.tasks, request=request)
        assert TaskAssignment.objects.count() == 0


class TestAnnotatorsColumnAndFilter(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory()
        cls.project = ProjectFactory(organization=cls.organization)
        cls.owner = cls.organization.created_by
        cls.annotator = UserFactory(active_organization=cls.organization)
        cls.task1 = TaskFactory(project=cls.project)
        cls.task2 = TaskFactory(project=cls.project)

    def test_annotators_column_unions_assignments(self):
        from data_manager.managers import annotate_annotators

        AnnotationFactory(task=self.task1, completed_by=self.owner)
        TaskAssignment.assign_to(self.task1, self.annotator)

        qs = annotate_annotators(Task.objects.filter(pk=self.task1.pk))
        annotator_ids = set(map(int, qs.first().annotators.split(',')))
        assert annotator_ids == {self.owner.id, self.annotator.id}

    def test_annotators_filter_matches_assigned_users(self):
        from data_manager.managers import apply_filters

        AnnotationFactory(task=self.task1, completed_by=self.owner)
        TaskAssignment.assign_to(self.task2, self.annotator)

        request = make_request(self.owner)
        filters = Filters(
            conjunction='and',
            items=[
                {
                    'filter': 'filter:tasks:annotators',
                    'operator': 'contains',
                    'type': 'List',
                    'value': str(self.annotator.id),
                }
            ],
        )
        qs = apply_filters(Task.objects.filter(project=self.project), filters, self.project, request)
        assert list(qs.values_list('id', flat=True)) == [self.task2.id]

        # not_contains: task2 is excluded (assigned), task1 stays (owner's annotation)
        filters = Filters(
            conjunction='and',
            items=[
                {
                    'filter': 'filter:tasks:annotators',
                    'operator': 'not_contains',
                    'type': 'List',
                    'value': str(self.annotator.id),
                }
            ],
        )
        qs = apply_filters(Task.objects.filter(project=self.project), filters, self.project, request)
        assert list(qs.values_list('id', flat=True)) == [self.task1.id]

        # empty: all tasks have annotators now (annotation on t1, assignment on t2)
        filters = Filters(
            conjunction='and',
            items=[
                {'filter': 'filter:tasks:annotators', 'operator': 'empty', 'type': 'List', 'value': 'true'}
            ],
        )
        qs = apply_filters(Task.objects.filter(project=self.project), filters, self.project, request)
        assert qs.count() == 0


class TestAssignedColumns(TestCase):
    """`assigned_annotators` / `assigned_reviewers` Data Manager columns."""

    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory()
        cls.project = ProjectFactory(organization=cls.organization)
        cls.owner = cls.organization.created_by
        cls.annotator = UserFactory(active_organization=cls.organization)
        cls.reviewer = UserFactory(active_organization=cls.organization)
        cls.task1 = TaskFactory(project=cls.project)
        cls.task2 = TaskFactory(project=cls.project)

    def _apply(self, filters_dict):
        from data_manager.managers import apply_filters

        filters = Filters(conjunction='and', items=[filters_dict])
        return apply_filters(Task.objects.filter(project=self.project), filters, self.project, make_request(self.owner))

    def test_annotate_assigned_columns_per_role(self):
        from tasks.functions import annotate_assigned_annotators, annotate_assigned_reviewers

        TaskAssignment.assign_to(self.task1, self.annotator)
        TaskAssignment.assign_to(self.task1, self.reviewer, role=TaskAssignment.Role.REVIEWER)
        TaskAssignment.assign_to(self.task2, self.reviewer, role=TaskAssignment.Role.REVIEWER)

        qs = annotate_assigned_annotators(Task.objects.filter(project=self.project))
        by_id = {t.id: t.assigned_annotators for t in qs}
        assert by_id[self.task1.id] == str(self.annotator.id)
        assert by_id[self.task2.id] == ''

        qs = annotate_assigned_reviewers(Task.objects.filter(project=self.project))
        by_id = {t.id: t.assigned_reviewers for t in qs}
        assert by_id[self.task1.id] == str(self.reviewer.id)
        assert by_id[self.task2.id] == str(self.reviewer.id)

    def test_serializer_parses_assigned_columns(self):
        from data_manager.serializers import DataManagerTaskSerializer
        from tasks.functions import annotate_assigned_annotators

        TaskAssignment.assign_to(self.task1, self.annotator)
        task = annotate_assigned_annotators(Task.objects.filter(pk=self.task1.pk)).first()
        assert DataManagerTaskSerializer._user_id_list(task, 'assigned_annotators') == [self.annotator.id]
        assert DataManagerTaskSerializer._user_id_list(task, 'assigned_reviewers') == []

    def test_assigned_annotators_filter(self):
        TaskAssignment.assign_to(self.task1, self.annotator)
        TaskAssignment.assign_to(self.task2, self.reviewer, role=TaskAssignment.Role.REVIEWER)

        qs = self._apply(
            {
                'filter': 'filter:tasks:assigned_annotators',
                'operator': 'contains',
                'type': 'List',
                'value': str(self.annotator.id),
            }
        )
        assert list(qs.values_list('id', flat=True)) == [self.task1.id]

        qs = self._apply(
            {
                'filter': 'filter:tasks:assigned_reviewers',
                'operator': 'contains',
                'type': 'List',
                'value': str(self.reviewer.id),
            }
        )
        assert list(qs.values_list('id', flat=True)) == [self.task2.id]

        qs = self._apply(
            {'filter': 'filter:tasks:assigned_annotators', 'operator': 'empty', 'type': 'List', 'value': 'true'}
        )
        assert list(qs.values_list('id', flat=True)) == [self.task2.id]

    def test_column_defs_and_filter_enum(self):
        from data_manager.functions import get_all_columns
        from data_manager.prepare_params import Column

        column_ids = {c['id'] for c in get_all_columns(self.project)['columns']}
        assert 'assigned_annotators' in column_ids
        assert 'assigned_reviewers' in column_ids
        assert 'filter:tasks:assigned_annotators' in Column.enums_for_filters()
        assert 'filter:tasks:assigned_reviewers' in Column.enums_for_filters()


class TestAssignedQueueSemantics(TestCase):
    """Assignment rows also unblock serving is_labeled tasks to assignees (assigned_flag)."""

    @classmethod
    def setUpTestData(cls):
        from organizations.models import OrganizationMember, OrganizationMemberRole

        cls.organization = OrganizationFactory()
        cls.project = ProjectFactory(organization=cls.organization)
        cls.owner = cls.organization.created_by
        cls.annotator = UserFactory(active_organization=cls.organization)
        # real annotator org role so is_annotator is truthy (not just the
        # is_project_annotator patch) — reviewer-capable roles get served
        # foreign annotations pending review by the review queue
        OrganizationMember.objects.filter(user=cls.annotator, organization=cls.organization).update(
            role=OrganizationMemberRole.ANNOTATOR
        )
        cls.other = UserFactory(active_organization=cls.organization)
        cls.task1 = TaskFactory(project=cls.project)

    def test_assigned_task_served_despite_is_labeled(self):
        # task labeled by someone else; with assigned_flag it's still served to the assignee
        self.task1.is_labeled = True
        self.task1.save()
        AnnotationFactory(task=self.task1, completed_by=self.other)
        TaskAssignment.assign_to(self.task1, self.annotator)

        tasks = Task.objects.filter(project=self.project).order_by('id')
        with as_annotator(self.annotator):
            scoped, flag = scope_tasks_to_assignments(self.annotator, self.project, tasks)
            next_task, _ = get_next_task(
                self.annotator, scoped, self.project, dm_queue=None, assigned_flag=flag
            )
            assert next_task is not None
            assert next_task.id == self.task1.id

            # and once the annotator solved it, the queue is empty
            AnnotationFactory(task=self.task1, completed_by=self.annotator)
            scoped, flag = scope_tasks_to_assignments(self.annotator, self.project, tasks)
            next_task, _ = get_next_task(
                self.annotator, scoped, self.project, dm_queue=None, assigned_flag=flag
            )
            assert next_task is None

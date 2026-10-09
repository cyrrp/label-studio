"""Tests for tasks.agreement (IAA / precomputed_agreement).

Covers:
- annotation_agreement: pairwise math over result payloads
- get_task_agreement: finished-annotation eligibility + pairwise averaging
- update_task_agreement + signal receivers: precomputed_agreement lifecycle
- get_tasks_agreement_queryset: _agreement (percent) + annotator_count
- Data Manager plumbing: annotate_agreement, agreement filter, serializer field
"""
import pytest
from data_manager.managers import annotate_agreement
from data_manager.prepare_params import Filters, ConjunctionEnum, Filter, PrepareParams
from data_manager.serializers import DataManagerTaskSerializer
from organizations.tests.factories import OrganizationFactory
from projects.tests.factories import ProjectFactory
from rest_framework.test import APITestCase
from tasks.agreement import (
    annotation_agreement,
    get_task_agreement,
    get_tasks_agreement_queryset,
    update_task_agreement,
)
from tasks.models import Task
from tasks.tests.factories import AnnotationFactory, TaskFactory
from users.tests.factories import UserFactory


def _choices(from_name, *labels):
    return {'from_name': from_name, 'to_name': 'text', 'type': 'choices', 'value': {'choices': list(labels)}}


def _rect(from_name, x, y, w, h, *labels):
    return {
        'from_name': from_name,
        'to_name': 'img',
        'type': 'rectanglelabels',
        'value': {'x': x, 'y': y, 'width': w, 'height': h, 'rectanglelabels': list(labels)},
    }


class TestAnnotationAgreement:
    """Pure pairwise math, no DB needed."""

    def test_identical_choices_agree(self):
        r1 = [_choices('c', 'A')]
        r2 = [_choices('c', 'A')]
        assert annotation_agreement(r1, r2) == pytest.approx(1.0)

    def test_disjoint_choices_disagree(self):
        r1 = [_choices('c', 'A')]
        r2 = [_choices('c', 'B')]
        assert annotation_agreement(r1, r2) == pytest.approx(0.0)

    def test_partial_overlap_is_jaccard(self):
        r1 = [_choices('c', 'A', 'B')]
        r2 = [_choices('c', 'B', 'C')]
        assert annotation_agreement(r1, r2) == pytest.approx(1 / 3)

    def test_scalar_rating(self):
        r1 = [{'from_name': 'r', 'to_name': 't', 'type': 'rating', 'value': {'rating': 4}}]
        r2 = [{'from_name': 'r', 'to_name': 't', 'type': 'rating', 'value': {'rating': 4}}]
        r3 = [{'from_name': 'r', 'to_name': 't', 'type': 'rating', 'value': {'rating': 2}}]
        assert annotation_agreement(r1, r2) == pytest.approx(1.0)
        assert annotation_agreement(r1, r3) == pytest.approx(0.0)

    def test_control_in_one_annotation_only_scores_zero(self):
        r1 = [_choices('c', 'A'), _choices('d', 'X')]
        r2 = [_choices('c', 'A')]
        # 'd' contributes 0 -> mean(1.0, 0.0)
        assert annotation_agreement(r1, r2) == pytest.approx(0.5)

    def test_multiple_controls_averaged(self):
        r1 = [_choices('c', 'A'), _choices('d', 'X')]
        r2 = [_choices('c', 'A'), _choices('d', 'Y')]
        assert annotation_agreement(r1, r2) == pytest.approx(0.5)

    def test_taxonomy_paths(self):
        r1 = [{'from_name': 't', 'to_name': 'x', 'type': 'taxonomy', 'value': {'taxonomy': [['a', 'b']]}}]
        r2 = [{'from_name': 't', 'to_name': 'x', 'type': 'taxonomy', 'value': {'taxonomy': [['a', 'b']]}}]
        r3 = [{'from_name': 't', 'to_name': 'x', 'type': 'taxonomy', 'value': {'taxonomy': [['a', 'c']]}}]
        assert annotation_agreement(r1, r2) == pytest.approx(1.0)
        assert annotation_agreement(r1, r3) == pytest.approx(0.0)

    def test_both_empty_results_agree(self):
        assert annotation_agreement([], []) == pytest.approx(1.0)
        assert annotation_agreement(None, None) == pytest.approx(1.0)

    def test_empty_vs_nonempty_disagree(self):
        assert annotation_agreement([], [_choices('c', 'A')]) == pytest.approx(0.0)

    def test_rectangles_same_box_same_label(self):
        r1 = [_rect('bbox', 0, 0, 50, 50, 'car')]
        r2 = [_rect('bbox', 0, 0, 50, 50, 'car')]
        assert annotation_agreement(r1, r2) == pytest.approx(1.0)

    def test_rectangles_same_box_different_label(self):
        r1 = [_rect('bbox', 0, 0, 50, 50, 'car')]
        r2 = [_rect('bbox', 0, 0, 50, 50, 'truck')]
        assert annotation_agreement(r1, r2) == pytest.approx(0.0)

    def test_rectangles_no_overlap(self):
        r1 = [_rect('bbox', 0, 0, 20, 20, 'car')]
        r2 = [_rect('bbox', 60, 60, 20, 20, 'car')]
        assert annotation_agreement(r1, r2) == pytest.approx(0.0)

    def test_rectangles_unmatched_region_scores_zero(self):
        r1 = [_rect('bbox', 0, 0, 20, 20, 'car'), _rect('bbox', 60, 60, 20, 20, 'car')]
        r2 = [_rect('bbox', 0, 0, 20, 20, 'car')]
        # one matched pair (1.0) + one unmatched (0) over union size 2
        assert annotation_agreement(r1, r2) == pytest.approx(0.5)


class TestTaskAgreementComputation(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory(created_by_active_organization=True)
        cls.project = ProjectFactory(organization=cls.organization)
        cls.user = cls.organization.created_by
        cls.other_user = UserFactory(active_organization=cls.organization)

    def _annotation(self, task, user, result, **kwargs):
        return AnnotationFactory(task=task, completed_by=user, result=result, **kwargs)

    def test_no_annotations_returns_none(self):
        task = TaskFactory(project=self.project)
        assert get_task_agreement(task) is None

    def test_single_annotation_returns_none(self):
        task = TaskFactory(project=self.project)
        self._annotation(task, self.user, [_choices('c', 'A')])
        assert get_task_agreement(task) is None

    def test_identical_annotations_full_agreement(self):
        task = TaskFactory(project=self.project)
        self._annotation(task, self.user, [_choices('c', 'A')])
        self._annotation(task, self.other_user, [_choices('c', 'A')])
        assert get_task_agreement(task) == pytest.approx(1.0)

    def test_different_annotations_zero_agreement(self):
        task = TaskFactory(project=self.project)
        self._annotation(task, self.user, [_choices('c', 'A')])
        self._annotation(task, self.other_user, [_choices('c', 'B')])
        assert get_task_agreement(task) == pytest.approx(0.0)

    def test_three_annotations_averaged(self):
        task = TaskFactory(project=self.project)
        self._annotation(task, self.user, [_choices('c', 'A')])
        self._annotation(task, self.other_user, [_choices('c', 'A')])
        third = UserFactory(active_organization=self.organization)
        self._annotation(task, third, [_choices('c', 'B')])
        # pairs: (1,2)=1.0, (1,3)=0.0, (2,3)=0.0 -> 1/3
        assert get_task_agreement(task) == pytest.approx(1 / 3)

    def test_cancelled_annotations_excluded(self):
        task = TaskFactory(project=self.project)
        self._annotation(task, self.user, [_choices('c', 'A')])
        self._annotation(task, self.other_user, [_choices('c', 'B')], was_cancelled=True)
        assert get_task_agreement(task) is None

    def test_ground_truth_annotations_excluded(self):
        task = TaskFactory(project=self.project)
        self._annotation(task, self.user, [_choices('c', 'A')])
        self._annotation(task, self.other_user, [_choices('c', 'B')], ground_truth=True)
        assert get_task_agreement(task) is None

    def test_null_result_annotations_excluded(self):
        task = TaskFactory(project=self.project)
        self._annotation(task, self.user, [_choices('c', 'A')])
        self._annotation(task, self.other_user, None)
        assert get_task_agreement(task) is None

    def test_null_completed_by_annotations_excluded(self):
        task = TaskFactory(project=self.project)
        self._annotation(task, self.user, [_choices('c', 'A')])
        AnnotationFactory(task=task, completed_by=None, result=[_choices('c', 'A')])
        assert get_task_agreement(task) is None


class TestUpdateTaskAgreement(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory(created_by_active_organization=True)
        cls.project = ProjectFactory(organization=cls.organization)
        cls.user = cls.organization.created_by
        cls.other_user = UserFactory(active_organization=cls.organization)

    def test_update_writes_precomputed_agreement(self):
        task = TaskFactory(project=self.project)
        AnnotationFactory(task=task, completed_by=self.user, result=[_choices('c', 'A')])
        AnnotationFactory(task=task, completed_by=self.other_user, result=[_choices('c', 'B')])
        agreement = update_task_agreement(task)
        task.refresh_from_db()
        assert agreement == pytest.approx(0.0)
        assert task.precomputed_agreement == pytest.approx(0.0)

    def test_signal_recomputes_on_annotation_save(self):
        task = TaskFactory(project=self.project)
        a1 = AnnotationFactory(task=task, completed_by=self.user, result=[_choices('c', 'A')])
        task.refresh_from_db()
        assert task.precomputed_agreement is None
        AnnotationFactory(task=task, completed_by=self.other_user, result=[_choices('c', 'A')])
        task.refresh_from_db()
        assert task.precomputed_agreement == pytest.approx(1.0)
        # update result -> recompute
        a1.result = [_choices('c', 'B')]
        a1.save()
        task.refresh_from_db()
        assert task.precomputed_agreement == pytest.approx(0.0)

    def test_signal_recomputes_on_annotation_delete(self):
        task = TaskFactory(project=self.project)
        AnnotationFactory(task=task, completed_by=self.user, result=[_choices('c', 'A')])
        a2 = AnnotationFactory(task=task, completed_by=self.other_user, result=[_choices('c', 'B')])
        task.refresh_from_db()
        assert task.precomputed_agreement == pytest.approx(0.0)
        a2.delete()
        task.refresh_from_db()
        assert task.precomputed_agreement is None

    def test_signal_recomputes_on_bulk_create(self):
        from tasks.models import Annotation

        task = TaskFactory(project=self.project)
        Annotation.objects.bulk_create(
            [
                Annotation(task=task, project=self.project, completed_by=self.user, result=[_choices('c', 'A')]),
                Annotation(task=task, project=self.project, completed_by=self.other_user, result=[_choices('c', 'A')]),
            ]
        )
        task.refresh_from_db()
        assert task.precomputed_agreement == pytest.approx(1.0)


class TestTasksAgreementQueryset(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory(created_by_active_organization=True)
        cls.project = ProjectFactory(organization=cls.organization)
        cls.user = cls.organization.created_by
        cls.other_user = UserFactory(active_organization=cls.organization)

    def test_queryset_annotations(self):
        task = TaskFactory(project=self.project)
        AnnotationFactory(task=task, completed_by=self.user, result=[_choices('c', 'A')])
        AnnotationFactory(task=task, completed_by=self.other_user, result=[_choices('c', 'A')])
        qs = get_tasks_agreement_queryset(Task.objects.filter(pk=task.pk))
        row = qs.first()
        assert row._agreement == pytest.approx(100.0)
        assert row.annotator_count == 2

    def test_annotator_count_excludes_cancelled_and_gt(self):
        task = TaskFactory(project=self.project)
        AnnotationFactory(task=task, completed_by=self.user, result=[_choices('c', 'A')])
        AnnotationFactory(task=task, completed_by=self.other_user, result=[_choices('c', 'A')])
        third = UserFactory(active_organization=self.organization)
        AnnotationFactory(task=task, completed_by=third, result=[_choices('c', 'B')], was_cancelled=True)
        fourth = UserFactory(active_organization=self.organization)
        AnnotationFactory(task=task, completed_by=fourth, result=[_choices('c', 'B')], ground_truth=True)
        row = get_tasks_agreement_queryset(Task.objects.filter(pk=task.pk)).first()
        assert row.annotator_count == 2

    def test_uncomputed_agreement_is_null(self):
        task = TaskFactory(project=self.project)
        row = get_tasks_agreement_queryset(Task.objects.filter(pk=task.pk)).first()
        assert row._agreement is None
        assert row.annotator_count == 0


class TestDataManagerAgreement(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory(created_by_active_organization=True)
        cls.project = ProjectFactory(organization=cls.organization)
        cls.user = cls.organization.created_by
        cls.other_user = UserFactory(active_organization=cls.organization)
        cls.task_agree = TaskFactory(project=cls.project)
        AnnotationFactory(task=cls.task_agree, completed_by=cls.user, result=[_choices('c', 'A')])
        AnnotationFactory(task=cls.task_agree, completed_by=cls.other_user, result=[_choices('c', 'A')])
        cls.task_disagree = TaskFactory(project=cls.project)
        AnnotationFactory(task=cls.task_disagree, completed_by=cls.user, result=[_choices('c', 'A')])
        AnnotationFactory(task=cls.task_disagree, completed_by=cls.other_user, result=[_choices('c', 'B')])

    def test_annotate_agreement_percent(self):
        qs = annotate_agreement(Task.objects.filter(pk=self.task_agree.pk))
        assert qs.first().agreement == pytest.approx(100.0)
        qs = annotate_agreement(Task.objects.filter(pk=self.task_disagree.pk))
        assert qs.first().agreement == pytest.approx(0.0)

    def test_serializer_exposes_agreement_percent(self):
        qs = annotate_agreement(Task.objects.filter(pk=self.task_agree.pk))
        data = DataManagerTaskSerializer(qs.first()).data
        assert data['agreement'] == pytest.approx(100.0)

    def test_serializer_falls_back_to_precomputed(self):
        task = Task.objects.get(pk=self.task_agree.pk)
        data = DataManagerTaskSerializer(task).data
        assert data['agreement'] == pytest.approx(100.0)

    def test_serializer_agreement_none_when_uncomputed(self):
        task = TaskFactory(project=self.project)
        data = DataManagerTaskSerializer(task).data
        assert data['agreement'] is None

    def _prepare_params(self, filter_item):
        return PrepareParams(
            project=self.project.id,
            filters=Filters(conjunction=ConjunctionEnum.AND, items=[filter_item]),
        )

    def test_filter_agreement_greater(self):
        params = self._prepare_params(
            Filter(filter='filter:tasks:agreement', operator='greater', type='Number', value=50)
        )
        qs = Task.prepared.only_filtered(prepare_params=params)
        ids = set(qs.values_list('id', flat=True))
        assert self.task_agree.id in ids
        assert self.task_disagree.id not in ids

    def test_filter_agreement_less_or_equal(self):
        params = self._prepare_params(
            Filter(filter='filter:tasks:agreement', operator='less_or_equal', type='Number', value=10)
        )
        qs = Task.prepared.only_filtered(prepare_params=params)
        ids = set(qs.values_list('id', flat=True))
        assert self.task_disagree.id in ids
        assert self.task_agree.id not in ids

    def test_filter_agreement_between(self):
        params = self._prepare_params(
            Filter(
                filter='filter:tasks:agreement',
                operator='in',
                type='Number',
                value={'min': 90, 'max': 100},
            )
        )
        qs = Task.prepared.only_filtered(prepare_params=params)
        ids = set(qs.values_list('id', flat=True))
        assert self.task_agree.id in ids
        assert self.task_disagree.id not in ids

    def test_ordering_by_agreement(self):
        params = PrepareParams(project=self.project.id, ordering=['-tasks:agreement'])
        qs = Task.prepared.only_filtered(prepare_params=params)
        ids = [t.id for t in qs]
        assert ids.index(self.task_agree.id) < ids.index(self.task_disagree.id)

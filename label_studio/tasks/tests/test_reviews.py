"""Tests for the community annotation review workflow.

Covers the AnnotationReview model, the review REST endpoints
(POST/GET /api/annotations/<id>/reviews/, RUD /api/annotation-reviews/<id>/),
serialized review state (`accepted_state`, `default_selected_annotation`)
and the rejected-rework queue in projects.functions.next_task.
"""

from unittest.mock import patch

from django.test import TestCase
from organizations.models import OrganizationMember, OrganizationMemberRole
from organizations.tests.factories import OrganizationFactory
from projects.functions.next_task import get_next_task
from projects.tests.factories import ProjectFactory
from rest_framework.test import APITestCase
from tasks.choices import ActionType, ReviewResult
from tasks.mixins import can_review
from tasks.models import Annotation, AnnotationReview, Task, TaskAssignment
from tasks.tests.factories import AnnotationFactory, AnnotationReviewFactory, TaskFactory
from users.tests.factories import UserFactory

RESULT_PAYLOAD = [{'id': 'r1', 'from_name': 'sentiment', 'to_name': 'text', 'type': 'choices', 'value': {'choices': ['Positive']}}]
FIXED_PAYLOAD = [{'id': 'r2', 'from_name': 'sentiment', 'to_name': 'text', 'type': 'choices', 'value': {'choices': ['Negative']}}]


def set_org_role(user, role, organization):
    """Set the user's org membership role (OW/AD/MA/RE/AN)."""
    OrganizationMember.objects.filter(user=user, organization=organization).update(role=role)


def reviews_url(annotation):
    return f'/api/annotations/{annotation.id}/reviews/'


def review_url(review):
    return f'/api/annotation-reviews/{review.id}/'


class ReviewWorkflowMixin:
    @classmethod
    def make_fixtures(cls):
        cls.organization = OrganizationFactory()
        cls.project = ProjectFactory(organization=cls.organization)
        cls.owner = cls.organization.created_by

        cls.annotator = UserFactory(active_organization=cls.organization)
        set_org_role(cls.annotator, OrganizationMemberRole.ANNOTATOR, cls.organization)

        cls.reviewer = UserFactory(active_organization=cls.organization)
        set_org_role(cls.reviewer, OrganizationMemberRole.REVIEWER, cls.organization)

        cls.other_reviewer = UserFactory(active_organization=cls.organization)
        set_org_role(cls.other_reviewer, OrganizationMemberRole.REVIEWER, cls.organization)

        cls.task = TaskFactory(project=cls.project)
        cls.annotation = AnnotationFactory(
            task=cls.task, completed_by=cls.annotator, result=RESULT_PAYLOAD
        )


class TestCanReview(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory()
        cls.project = ProjectFactory(organization=cls.organization)
        cls.owner = cls.organization.created_by
        cls.annotator = UserFactory(active_organization=cls.organization)
        set_org_role(cls.annotator, OrganizationMemberRole.ANNOTATOR, cls.organization)
        cls.reviewer = UserFactory(active_organization=cls.organization)
        set_org_role(cls.reviewer, OrganizationMemberRole.REVIEWER, cls.organization)
        cls.task = TaskFactory(project=cls.project)

    def test_anonymous_cannot_review(self):
        from django.contrib.auth.models import AnonymousUser

        assert can_review(AnonymousUser(), self.task) is False

    def test_management_and_reviewer_can_review(self):
        assert can_review(self.owner, self.task) is True
        assert can_review(self.reviewer, self.task) is True

    def test_annotator_needs_reviewer_assignment(self):
        assert can_review(self.annotator, self.task) is False
        TaskAssignment.assign_to(self.task, self.annotator, role=TaskAssignment.Role.REVIEWER)
        assert can_review(self.annotator, self.task) is True


class TestAnnotationReviewModel(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory()
        cls.project = ProjectFactory(organization=cls.organization)
        cls.owner = cls.organization.created_by
        cls.task = TaskFactory(project=cls.project)
        cls.annotation = AnnotationFactory(task=cls.task, completed_by=cls.owner)

    def test_unique_per_annotation_and_reviewer(self):
        AnnotationReviewFactory(
            annotation=self.annotation, created_by=self.owner, result=ReviewResult.ACCEPTED
        )
        from django.db import IntegrityError
        from django.db import transaction as db_transaction

        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                AnnotationReview.objects.create(
                    annotation=self.annotation,
                    created_by=self.owner,
                    result=ReviewResult.REJECTED,
                )

        # a different reviewer can still review the same annotation
        other = UserFactory(active_organization=self.organization)
        AnnotationReview.objects.create(
            annotation=self.annotation, created_by=other, result=ReviewResult.REJECTED
        )
        assert self.annotation.reviews.count() == 2


class TestReviewAPI(ReviewWorkflowMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def test_post_accept_creates_review_and_sets_last_action(self):
        self.client.force_authenticate(user=self.reviewer)
        response = self.client.post(reviews_url(self.annotation), {'result': 'accepted'}, format='json')
        assert response.status_code == 201, response.content

        review = AnnotationReview.objects.get()
        assert review.result == ReviewResult.ACCEPTED
        assert review.created_by == self.reviewer

        self.annotation.refresh_from_db()
        assert self.annotation.last_action == ActionType.ACCEPTED

        # accepted_state exposed on the annotation payload
        response = self.client.get(f'/api/annotations/{self.annotation.id}/')
        assert response.status_code == 200
        assert response.json()['accepted_state'] == 'accepted'

    def test_post_reject_with_comment(self):
        self.client.force_authenticate(user=self.reviewer)
        response = self.client.post(
            reviews_url(self.annotation),
            {'result': 'rejected', 'comment': 'please fix labels'},
            format='json',
        )
        assert response.status_code == 201, response.content
        review = AnnotationReview.objects.get()
        assert review.result == ReviewResult.REJECTED
        assert review.comment == 'please fix labels'
        self.annotation.refresh_from_db()
        assert self.annotation.last_action == ActionType.REJECTED

    def test_post_upserts_per_reviewer(self):
        self.client.force_authenticate(user=self.reviewer)
        self.client.post(reviews_url(self.annotation), {'result': 'rejected'}, format='json')
        response = self.client.post(reviews_url(self.annotation), {'result': 'accepted'}, format='json')
        assert response.status_code == 200
        assert AnnotationReview.objects.count() == 1
        assert AnnotationReview.objects.get().result == ReviewResult.ACCEPTED

    def test_post_legacy_accepted_boolean_payloads(self):
        self.client.force_authenticate(user=self.reviewer)
        response = self.client.post(reviews_url(self.annotation), {'accepted': True}, format='json')
        assert response.status_code == 201, response.content
        assert response.json()['result'] == 'accepted'

        response = self.client.post(reviews_url(self.annotation), {'accepted': False}, format='json')
        assert response.status_code == 200
        assert AnnotationReview.objects.get().result == ReviewResult.REJECTED

    def test_post_legacy_fixed_result(self):
        self.client.force_authenticate(user=self.reviewer)
        response = self.client.post(reviews_url(self.annotation), {'result': 'fixed'}, format='json')
        assert response.status_code == 201, response.content
        assert response.json()['result'] == 'fixed_and_accepted'
        self.annotation.refresh_from_db()
        assert self.annotation.last_action == ReviewResult.FIXED_AND_ACCEPTED

    def test_post_fix_and_accept_replaces_annotation_result(self):
        self.client.force_authenticate(user=self.reviewer)
        response = self.client.post(
            reviews_url(self.annotation),
            {'result': 'accepted', 'annotation_result': FIXED_PAYLOAD},
            format='json',
        )
        assert response.status_code == 201, response.content
        review = AnnotationReview.objects.get()
        assert review.result == ReviewResult.FIXED_AND_ACCEPTED
        self.annotation.refresh_from_db()
        assert self.annotation.result == FIXED_PAYLOAD

    def test_cannot_review_own_annotation(self):
        own_annotation = AnnotationFactory(task=self.task, completed_by=self.reviewer)
        self.client.force_authenticate(user=self.reviewer)
        response = self.client.post(reviews_url(own_annotation), {'result': 'accepted'}, format='json')
        assert response.status_code == 400

    def test_annotator_cannot_review_without_reviewer_assignment(self):
        foreign = AnnotationFactory(task=self.task, completed_by=self.owner)
        TaskAssignment.assign_to(self.task, self.annotator)

        self.client.force_authenticate(user=self.annotator)
        response = self.client.post(reviews_url(foreign), {'result': 'accepted'}, format='json')
        assert response.status_code == 403

        # an explicit reviewer assignment unlocks it
        TaskAssignment.assign_to(self.task, self.annotator, role=TaskAssignment.Role.REVIEWER)
        response = self.client.post(reviews_url(foreign), {'result': 'accepted'}, format='json')
        assert response.status_code == 201, response.content

    def test_list_reviews(self):
        AnnotationReviewFactory(
            annotation=self.annotation, created_by=self.reviewer, result=ReviewResult.ACCEPTED
        )
        AnnotationReviewFactory(
            annotation=self.annotation, created_by=self.owner, result=ReviewResult.REJECTED
        )
        self.client.force_authenticate(user=self.reviewer)
        response = self.client.get(reviews_url(self.annotation))
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert {r['result'] for r in data} == {'accepted', 'rejected'}
        assert all('created_by' in r for r in data)

    def test_invalid_result_rejected(self):
        self.client.force_authenticate(user=self.reviewer)
        response = self.client.post(reviews_url(self.annotation), {'result': 'bogus'}, format='json')
        assert response.status_code == 400

    def test_unauthenticated_cannot_review(self):
        response = self.client.post(reviews_url(self.annotation), {'result': 'accepted'}, format='json')
        assert response.status_code in (401, 403)


class TestReviewModifyAPI(ReviewWorkflowMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()
        cls.review = AnnotationReviewFactory(
            annotation=cls.annotation, created_by=cls.reviewer, result=ReviewResult.REJECTED
        )

    def test_author_can_patch_own_review(self):
        self.client.force_authenticate(user=self.reviewer)
        response = self.client.patch(
            review_url(self.review), {'result': 'accepted'}, format='json'
        )
        assert response.status_code == 200, response.content
        self.review.refresh_from_db()
        assert self.review.result == ReviewResult.ACCEPTED
        self.annotation.refresh_from_db()
        assert self.annotation.last_action == ActionType.ACCEPTED

    def test_other_reviewer_cannot_patch(self):
        self.client.force_authenticate(user=self.other_reviewer)
        response = self.client.patch(
            review_url(self.review), {'result': 'accepted'}, format='json'
        )
        assert response.status_code == 403

    def test_management_can_patch(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            review_url(self.review), {'comment': 'overridden'}, format='json'
        )
        assert response.status_code == 200, response.content
        self.review.refresh_from_db()
        assert self.review.comment == 'overridden'
        # result unchanged
        assert self.review.result == ReviewResult.REJECTED

    def test_patch_with_annotation_result_forces_fixed(self):
        self.client.force_authenticate(user=self.reviewer)
        response = self.client.patch(
            review_url(self.review), {'annotation_result': FIXED_PAYLOAD}, format='json'
        )
        assert response.status_code == 200, response.content
        self.review.refresh_from_db()
        assert self.review.result == ReviewResult.FIXED_AND_ACCEPTED
        self.annotation.refresh_from_db()
        assert self.annotation.result == FIXED_PAYLOAD

    def test_delete_resets_review_state(self):
        self.annotation.last_action = ActionType.REJECTED
        self.annotation.save(update_fields=['last_action'])

        self.client.force_authenticate(user=self.reviewer)
        response = self.client.delete(review_url(self.review))
        assert response.status_code == 204
        assert not AnnotationReview.objects.filter(pk=self.review.pk).exists()

        self.annotation.refresh_from_db()
        assert self.annotation.last_action == ActionType.DELETED_REVIEW

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(f'/api/annotations/{self.annotation.id}/')
        assert response.json()['accepted_state'] is None


class TestRejectedQueue(ReviewWorkflowMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()
        cls.prepared = Task.objects.filter(project=cls.project)

    def _next(self, user):
        return get_next_task(user, self.prepared, self.project, dm_queue=None, assigned_flag=False)

    def test_rejected_task_is_served_back_to_annotator(self):
        AnnotationReviewFactory(
            annotation=self.annotation, created_by=self.reviewer, result=ReviewResult.REJECTED
        )
        next_task, queue_info = self._next(self.annotator)
        assert next_task is not None
        assert next_task.id == self.task.id
        assert 'Rejected queue' in queue_info

    def test_accepted_task_is_not_requeued(self):
        AnnotationReviewFactory(
            annotation=self.annotation, created_by=self.reviewer, result=ReviewResult.ACCEPTED
        )
        next_task, _ = self._next(self.annotator)
        assert next_task is None

    def test_reworked_annotation_stops_being_rejected(self):
        AnnotationReviewFactory(
            annotation=self.annotation, created_by=self.reviewer, result=ReviewResult.REJECTED
        )
        # annotator reworks -> annotation.updated_at becomes newer than the review
        self.annotation.result = FIXED_PAYLOAD
        self.annotation.save()

        next_task, _ = self._next(self.annotator)
        assert next_task is None

    def test_other_users_annotations_are_not_served(self):
        other = UserFactory(active_organization=self.organization)
        annotation = AnnotationFactory(task=self.task, completed_by=other)
        AnnotationReviewFactory(annotation=annotation, created_by=self.reviewer, result=ReviewResult.REJECTED)
        # annotator has no rejected work of their own
        next_task, _ = self._next(self.annotator)
        assert next_task is None or next_task.id != self.task.id


class TestDefaultSelectedAnnotation(ReviewWorkflowMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def test_annotator_gets_rejected_annotation_as_default(self):
        # annotators are scoped to their assignments (scope_tasks_to_assignments)
        TaskAssignment.assign_to(self.task, self.annotator)
        AnnotationReviewFactory(
            annotation=self.annotation, created_by=self.reviewer, result=ReviewResult.REJECTED
        )
        self.client.force_authenticate(user=self.annotator)
        response = self.client.get(f'/api/projects/{self.project.id}/next/')
        assert response.status_code == 200, response.content
        data = response.json()
        assert data['default_selected_annotation'] == self.annotation.id
        # the rejected annotation is shipped so the editor can open it
        annotation_ids = [a['id'] for a in data['annotations']]
        assert self.annotation.id in annotation_ids

    def test_reviewer_gets_first_pending_foreign_annotation(self):
        # a fully labeled task must still be served to reviewers for review
        self.task.is_labeled = True
        self.task.save(update_fields=['is_labeled'])

        self.client.force_authenticate(user=self.reviewer)
        response = self.client.get(f'/api/projects/{self.project.id}/next/')
        assert response.status_code == 200, response.content
        data = response.json()
        assert data['default_selected_annotation'] == self.annotation.id
        assert data['queue'] == 'Review queue'
        assert self.annotation.id in [a['id'] for a in data['annotations']]

        # after the reviewer reviewed it, nothing is left pending -> stream ends
        AnnotationReviewFactory(
            annotation=self.annotation, created_by=self.reviewer, result=ReviewResult.ACCEPTED
        )
        response = self.client.get(f'/api/projects/{self.project.id}/next/')
        assert response.status_code == 404


class TestTaskReviewColumns(ReviewWorkflowMixin, TestCase):
    """Data Manager column annotations registered from tasks.functions."""

    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def test_annotation_functions(self):
        from tasks.functions import (
            annotate_reviewed,
            annotate_reviewed_at,
            annotate_reviewers,
            annotate_reviews_accepted,
            annotate_reviews_rejected,
        )

        qs = Task.objects.filter(pk=self.task.pk)
        qs = annotate_reviewed_at(annotate_reviews_accepted(annotate_reviews_rejected(annotate_reviewers(annotate_reviewed(qs)))))
        task = qs.first()
        assert task.reviewed is False
        assert task.reviews_accepted == 0
        assert task.reviews_rejected == 0

        AnnotationReviewFactory(
            annotation=self.annotation, created_by=self.reviewer, result=ReviewResult.ACCEPTED
        )
        qs = Task.objects.filter(pk=self.task.pk)
        qs = annotate_reviewed_at(annotate_reviews_accepted(annotate_reviews_rejected(annotate_reviewers(annotate_reviewed(qs)))))
        task = qs.first()
        assert task.reviewed is True
        assert task.reviews_accepted == 1
        assert task.reviews_rejected == 0
        assert str(self.reviewer.id) in (task.reviewers or '')
        assert task.reviewed_at is not None

        AnnotationReviewFactory(
            annotation=self.annotation, created_by=self.owner, result=ReviewResult.REJECTED
        )
        qs = Task.objects.filter(pk=self.task.pk)
        qs = annotate_reviews_rejected(annotate_reviews_accepted(qs))
        task = qs.first()
        assert task.reviews_rejected == 1
        assert task.reviews_accepted == 1


class TestReviewSerializerEdgeCases(TestCase):
    """Serializer-level compatibility shims (annotation field on reviews)."""

    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory()
        cls.project = ProjectFactory(organization=cls.organization)
        cls.owner = cls.organization.created_by
        cls.task = TaskFactory(project=cls.project)
        cls.annotation = AnnotationFactory(task=cls.task, completed_by=cls.owner)

    def test_review_payload_fields(self):
        from tasks.serializers import AnnotationReviewSerializer

        review = AnnotationReviewFactory(
            annotation=self.annotation,
            created_by=self.owner,
            result=ReviewResult.ACCEPTED,
            comment='ok',
        )
        data = AnnotationReviewSerializer(review).data
        assert data['result'] == 'accepted'
        assert data['accepted'] is True
        assert data['comment'] == 'ok'
        assert data['annotation'] == self.annotation.id
        assert data['created_by']['id'] == self.owner.id

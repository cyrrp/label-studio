"""Tests for the comments app (OSS implementation of the LSE comments contract).

Covers CRUD on /api/comments/, denormalized task/project sync,
org scoping, author/admin write permissions and resolve bookkeeping.
"""

from comments.models import Comment
from organizations.models import OrganizationMember, OrganizationMemberRole
from organizations.tests.factories import OrganizationFactory
from projects.tests.factories import ProjectFactory
from rest_framework.test import APITestCase
from tasks.models import TaskAssignment
from tasks.tests.factories import AnnotationDraftFactory, AnnotationFactory, TaskFactory
from users.tests.factories import UserFactory


def set_org_role(user, role, organization):
    OrganizationMember.objects.filter(user=user, organization=organization).update(role=role)


def comments_url():
    return '/api/comments/'


def comment_url(comment):
    return f'/api/comments/{comment.id}/'


class CommentAPITestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory()
        cls.project = ProjectFactory(organization=cls.organization)
        cls.owner = cls.organization.created_by

        cls.annotator = UserFactory(active_organization=cls.organization)
        set_org_role(cls.annotator, OrganizationMemberRole.ANNOTATOR, cls.organization)

        cls.other_user = UserFactory(active_organization=cls.organization)
        set_org_role(cls.other_user, OrganizationMemberRole.ANNOTATOR, cls.organization)

        cls.task = TaskFactory(project=cls.project)
        cls.annotation = AnnotationFactory(task=cls.task, completed_by=cls.annotator)

    def test_create_on_annotation_sets_denormalized_fields(self):
        self.client.force_authenticate(user=self.annotator)
        response = self.client.post(
            comments_url(), {'annotation': self.annotation.id, 'text': 'first'}, format='json'
        )
        assert response.status_code == 201, response.content
        comment = Comment.objects.get(id=response.json()['id'])
        assert comment.task_id == self.task.id
        assert comment.project_id == self.project.id
        assert comment.created_by_id == self.annotator.id

    def test_create_requires_target(self):
        self.client.force_authenticate(user=self.annotator)
        response = self.client.post(comments_url(), {'text': 'orphan'}, format='json')
        assert response.status_code == 400

    def test_create_on_draft_resolves_task(self):
        # annotators may only act on assigned tasks; give the annotator an assignment
        TaskAssignment.objects.create(task=self.task, user=self.annotator, role=TaskAssignment.Role.ANNOTATOR)
        draft = AnnotationDraftFactory(task=self.task, user=self.annotator)
        self.client.force_authenticate(user=self.annotator)
        response = self.client.post(comments_url(), {'draft': draft.id, 'text': 'wip'}, format='json')
        assert response.status_code == 201, response.content
        assert Comment.objects.get(id=response.json()['id']).task_id == self.task.id

    def test_list_filters_by_annotation_and_returns_plain_array(self):
        Comment.objects.create(annotation=self.annotation, text='a', created_by=self.annotator)
        other = AnnotationFactory(task=TaskFactory(project=self.project), completed_by=self.annotator)
        Comment.objects.create(annotation=other, text='b', created_by=self.annotator)

        self.client.force_authenticate(user=self.annotator)
        response = self.client.get(comments_url(), {'annotation': self.annotation.id})
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert [c['text'] for c in body] == ['a']

    def test_list_is_scoped_to_active_organization(self):
        other_org = OrganizationFactory()
        foreign = AnnotationFactory(
            task=TaskFactory(project=ProjectFactory(organization=other_org)),
            completed_by=self.annotator,
        )
        Comment.objects.create(annotation=foreign, text='foreign', created_by=self.annotator)

        self.client.force_authenticate(user=self.annotator)
        response = self.client.get(comments_url())
        assert response.status_code == 200
        assert response.json() == []

    def test_author_can_patch_and_resolve(self):
        comment = Comment.objects.create(annotation=self.annotation, text='a', created_by=self.annotator)
        self.client.force_authenticate(user=self.annotator)
        response = self.client.patch(comment_url(comment), {'text': 'edited', 'is_resolved': True}, format='json')
        assert response.status_code == 200, response.content
        comment.refresh_from_db()
        assert comment.text == 'edited'
        assert comment.is_resolved is True
        assert comment.resolved_at is not None

    def test_non_author_non_admin_cannot_patch(self):
        comment = Comment.objects.create(annotation=self.annotation, text='a', created_by=self.annotator)
        self.client.force_authenticate(user=self.other_user)
        response = self.client.patch(comment_url(comment), {'text': 'hijack'}, format='json')
        assert response.status_code == 403

    def test_admin_can_delete_foreign_comment(self):
        comment = Comment.objects.create(annotation=self.annotation, text='a', created_by=self.annotator)
        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(comment_url(comment))
        assert response.status_code == 204
        assert not Comment.objects.filter(id=comment.id).exists()

    def test_expand_created_by(self):
        Comment.objects.create(annotation=self.annotation, text='a', created_by=self.annotator)
        self.client.force_authenticate(user=self.annotator)
        response = self.client.get(comments_url(), {'annotation': self.annotation.id, 'expand_created_by': 'true'})
        assert response.status_code == 200
        created_by = response.json()[0]['created_by']
        assert isinstance(created_by, dict)
        assert created_by['id'] == self.annotator.id

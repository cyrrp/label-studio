from django.contrib.auth.models import AnonymousUser
from organizations.models import OrganizationMember, OrganizationMemberRole
from organizations.tests.factories import OrganizationFactory
from projects.tests.factories import ProjectFactory
from rest_framework.test import APITestCase
from users.tests.factories import UserFactory


class TestMemberRoles(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory()
        cls.owner = cls.organization.created_by
        cls.manager = UserFactory(active_organization=cls.organization)
        cls.annotator = UserFactory(active_organization=cls.organization)
        OrganizationMember.objects.filter(user=cls.annotator, organization=cls.organization).update(
            role=OrganizationMemberRole.ANNOTATOR
        )
        cls.reviewer = UserFactory(active_organization=cls.organization)
        OrganizationMember.objects.filter(user=cls.reviewer, organization=cls.organization).update(
            role=OrganizationMemberRole.REVIEWER
        )

    def set_membership_role(self, user, role):
        OrganizationMember.objects.filter(user=user, organization=self.organization).update(role=role)

    def test_creator_gets_owner_role(self):
        owner_member = OrganizationMember.objects.get(user=self.owner, organization=self.organization)
        assert owner_member.role == OrganizationMemberRole.OWNER
        assert owner_member.is_owner
        assert owner_member.is_admin

    def test_add_user_defaults_to_manager(self):
        user = UserFactory()
        member = self.organization.add_user(user)
        assert member.role == OrganizationMemberRole.MANAGER

    def test_add_user_with_explicit_role(self):
        user = UserFactory()
        member = self.organization.add_user(user, role=OrganizationMemberRole.ANNOTATOR)
        assert member.role == OrganizationMemberRole.ANNOTATOR

    def test_org_role_and_role_flags(self):
        assert self.owner.org_role == OrganizationMemberRole.OWNER
        assert self.manager.org_role == OrganizationMemberRole.MANAGER
        assert self.annotator.org_role == OrganizationMemberRole.ANNOTATOR
        assert self.reviewer.org_role == OrganizationMemberRole.REVIEWER

        assert self.annotator.is_annotator is True
        assert self.annotator.is_reviewer is False
        assert self.reviewer.is_reviewer is True
        assert self.manager.is_annotator is False
        assert self.manager.is_reviewer is False

    def test_org_role_none_without_active_org(self):
        user = UserFactory()  # no active organization, no membership
        assert user.org_role is None
        assert user.is_annotator is False
        assert user.is_reviewer is False
        assert user.is_organization_admin() is False

    def test_is_project_annotator(self):
        project = ProjectFactory(organization=self.organization)
        # no member restriction: any annotator may label
        assert self.annotator.is_project_annotator(project) is True
        # restricted roles only
        assert self.manager.is_project_annotator(project) is False
        assert self.reviewer.is_project_annotator(project) is False

        # restricted project: annotator must be a project member
        other = UserFactory(active_organization=self.organization)
        project.add_collaborator(other)
        assert self.annotator.is_project_annotator(project) is False
        self.set_membership_role(other, OrganizationMemberRole.ANNOTATOR)
        assert other.is_project_annotator(project) is True

    def test_is_organization_admin(self):
        assert self.owner.is_organization_admin(self.organization.pk) is True
        assert self.manager.is_organization_admin(self.organization.pk) is False
        assert self.annotator.is_organization_admin(self.organization.pk) is False

        self.set_membership_role(self.manager, OrganizationMemberRole.ADMINISTRATOR)
        assert self.manager.is_organization_admin(self.organization.pk) is True
        # falls back to the active organization
        assert self.manager.is_organization_admin() is True
        self.set_membership_role(self.manager, OrganizationMemberRole.MANAGER)

    def test_tasks_assign_permission(self):
        assert self.owner.has_perm('tasks.assign') is True
        assert self.manager.has_perm('tasks.assign') is True
        assert self.annotator.has_perm('tasks.assign') is False
        assert self.reviewer.has_perm('tasks.assign') is False

        self.set_membership_role(self.manager, OrganizationMemberRole.ADMINISTRATOR)
        assert self.manager.has_perm('tasks.assign') is True
        self.set_membership_role(self.manager, OrganizationMemberRole.MANAGER)

    def test_tasks_assign_permission_anonymous(self):
        # unauthenticated users are never assigners and must not raise
        assert AnonymousUser().has_perm('tasks.assign') is False

    def test_member_list_exposes_role(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(f'/api/organizations/{self.organization.id}/memberships')
        assert response.status_code == 200
        roles = {r['user']['id']: r['role'] for r in response.json()['results']}
        assert roles[self.owner.id] == 'OW'
        assert roles[self.manager.id] == 'MA'
        assert roles[self.annotator.id] == 'AN'

    def test_patch_member_role(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            f'/api/organizations/{self.organization.id}/memberships/{self.manager.id}/',
            {'role': 'AN'},
            format='json',
        )
        assert response.status_code == 200
        member = OrganizationMember.objects.get(user=self.manager, organization=self.organization)
        assert member.role == 'AN'
        assert response.json()['role'] == 'AN'

    def test_patch_member_role_forbidden_for_non_admin(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.patch(
            f'/api/organizations/{self.organization.id}/memberships/{self.annotator.id}/',
            {'role': 'MA'},
            format='json',
        )
        assert response.status_code == 403

        self.client.force_authenticate(user=self.annotator)
        response = self.client.patch(
            f'/api/organizations/{self.organization.id}/memberships/{self.manager.id}/',
            {'role': 'AN'},
            format='json',
        )
        assert response.status_code == 403

    def test_patch_member_role_allowed_for_admin(self):
        self.set_membership_role(self.manager, OrganizationMemberRole.ADMINISTRATOR)
        self.client.force_authenticate(user=self.manager)
        response = self.client.patch(
            f'/api/organizations/{self.organization.id}/memberships/{self.annotator.id}/',
            {'role': 'RE'},
            format='json',
        )
        assert response.status_code == 200
        member = OrganizationMember.objects.get(user=self.annotator, organization=self.organization)
        assert member.role == 'RE'

    def test_patch_member_role_invalid(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            f'/api/organizations/{self.organization.id}/memberships/{self.manager.id}/',
            {'role': 'XX'},
            format='json',
        )
        assert response.status_code == 400

    def test_patch_member_role_requires_auth(self):
        response = self.client.patch(
            f'/api/organizations/{self.organization.id}/memberships/{self.manager.id}/',
            {'role': 'AN'},
            format='json',
        )
        assert response.status_code in (401, 403)

    def test_whoami_exposes_role(self):
        self.client.force_authenticate(user=self.annotator)
        response = self.client.get('/api/current-user/whoami')
        assert response.status_code == 200
        assert response.json()['role'] == 'AN'

        self.client.force_authenticate(user=self.owner)
        response = self.client.get('/api/current-user/whoami')
        assert response.status_code == 200
        assert response.json()['role'] == 'OW'

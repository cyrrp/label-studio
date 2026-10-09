from django.utils.functional import cached_property


class OrganizationMixin:
    @cached_property
    def active_members(self):
        return self.members


class OrganizationMemberMixin:
    def has_permission(self, user):
        if user.active_organization_id == self.organization_id:
            return True
        return False

    @cached_property
    def is_admin(self):
        from organizations.models import OrganizationMemberRole

        return self.role in (OrganizationMemberRole.OWNER, OrganizationMemberRole.ADMINISTRATOR)

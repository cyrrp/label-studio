from organizations.models import OrganizationMember, OrganizationMemberRole


class UserMixin:
    @property
    def org_role(self):
        """Role code ('OW', 'AD', 'MA', 'RE', 'AN') of the user's membership
        in their active organization, or None."""
        if not getattr(self, 'is_authenticated', False) or not self.pk or not self.active_organization_id:
            return None
        # iterate to reuse prefetch_related('om_through') caches when available
        for membership in self.om_through.all():
            if membership.organization_id == self.active_organization_id and membership.deleted_at is None:
                return membership.role
        return None

    @property
    def is_annotator(self):
        return self.org_role == OrganizationMemberRole.ANNOTATOR

    @property
    def is_reviewer(self):
        return self.org_role == OrganizationMemberRole.REVIEWER

    def is_project_annotator(self, project):
        if not self.is_annotator or project is None:
            return False
        # project without explicit members has no member restriction
        if not project.members.exists():
            return True
        return project.members.filter(user_id=self.pk).exists()

    def has_permission(self, user):
        return OrganizationMember.objects.filter(
            user=user, organization=user.active_organization, deleted_at__isnull=True
        ).exists()

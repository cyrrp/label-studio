"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license.

Data Manager actions for manual task assignment (Community implementation of the
Enterprise assign/unassign annotators & reviewers feature).

Annotators (organization role 'AN') only see tasks assigned to them through
tasks.TaskAssignment; these actions let managers create and remove assignments
in bulk for the selected tasks.
"""
import logging

from core.permissions import all_permissions
from data_manager.actions import DataManagerAction
from rest_framework.exceptions import PermissionDenied
from tasks.models import TaskAssignment
from users.models import User

logger = logging.getLogger(__name__)

# 'tasks.assign' is granted to manager-level roles only (OW/AD/MA pass; AN/RE fail).
# Fall back to the literal so a missing AllPermissions field can't break action registration.
ASSIGN_PERMISSION = getattr(all_permissions, 'tasks_assign', 'tasks.assign')


def _get_selected_user_ids(request, field):
    """Parse user ids submitted by the assignment dialog form (single value or list)."""
    value = request.data.get(field)
    if value is None or value == '':
        return []
    if not isinstance(value, (list, tuple)):
        value = [value]
    user_ids = []
    for v in value:
        try:
            user_ids.append(int(v))
        except (TypeError, ValueError):
            logger.warning('Assignment action: skipping invalid user id "%s"', v)
    return user_ids


def _org_member_users(project, user_ids=None):
    """Users of the project's organization, optionally restricted to the given ids."""
    member_ids = project.organization.members.filter(deleted_at__isnull=True).values_list('user_id', flat=True)
    users = User.objects.filter(id__in=member_ids)
    if user_ids is not None:
        users = users.filter(id__in=user_ids)
    return users


def _check_can_assign(user):
    """Extra guard: annotators/reviewers can never run assignment actions, even if the
    permission predicate is wired too broadly."""
    if getattr(user, 'is_annotator', False) or getattr(user, 'is_reviewer', False):
        raise PermissionDenied('Only managers can assign tasks')


def _assign_role(project, queryset, request, role, users_field):
    """Create TaskAssignment rows for selected users on the given tasks."""
    _check_can_assign(request.user)
    user_ids = _get_selected_user_ids(request, users_field)
    users = list(_org_member_users(project, user_ids))
    role_label = TaskAssignment.Role(role).label

    if not user_ids:
        return {'processed_items': 0, 'detail': 'No users were selected for assignment'}
    if not users:
        return {'processed_items': 0, 'detail': 'Selected users are not members of this organization'}

    task_ids = list(queryset.values_list('id', flat=True))
    existing = set(
        TaskAssignment.objects.filter(task_id__in=task_ids, user__in=users, role=role).values_list(
            'task_id', 'user_id'
        )
    )
    to_create = [
        TaskAssignment(task_id=task_id, user_id=user.id, role=role, assigned_by=request.user)
        for task_id in task_ids
        for user in users
        if (task_id, user.id) not in existing
    ]
    if to_create:
        TaskAssignment.objects.bulk_create(to_create, ignore_conflicts=True)

    return {
        'processed_items': len(task_ids),
        'detail': (
            f'Assigned {len(users)} {role_label}(s) to {len(task_ids)} tasks '
            f'({len(to_create)} new assignments created)'
        ),
    }


def _unassign_role(project, queryset, request, role, users_field):
    """Delete TaskAssignment rows on the given tasks; empty user selection removes all."""
    _check_can_assign(request.user)
    user_ids = _get_selected_user_ids(request, users_field)
    assignments = TaskAssignment.objects.filter(task_id__in=queryset.values('id'), role=role)
    if user_ids:
        assignments = assignments.filter(user_id__in=user_ids)

    count = assignments.count()
    assignments.delete()

    role_label = TaskAssignment.Role(role).label
    scope = 'selected' if user_ids else 'all'
    return {
        'processed_items': count,
        'detail': f'Removed {count} {role_label} assignment(s) from {scope} users',
    }


def assign_annotators(project, queryset, **kwargs):
    """Assign annotators to selected tasks

    :param project: project instance
    :param queryset: filtered tasks db queryset
    """
    return _assign_role(project, queryset, kwargs['request'], TaskAssignment.Role.ANNOTATOR, 'annotators')


def delete_annotators(project, queryset, **kwargs):
    """Remove annotator assignments from selected tasks

    :param project: project instance
    :param queryset: filtered tasks db queryset
    """
    return _unassign_role(project, queryset, kwargs['request'], TaskAssignment.Role.ANNOTATOR, 'annotators')


def assign_reviewers(project, queryset, **kwargs):
    """Assign reviewers to selected tasks

    :param project: project instance
    :param queryset: filtered tasks db queryset
    """
    return _assign_role(project, queryset, kwargs['request'], TaskAssignment.Role.REVIEWER, 'reviewers')


def delete_reviewers(project, queryset, **kwargs):
    """Remove reviewer assignments from selected tasks

    :param project: project instance
    :param queryset: filtered tasks db queryset
    """
    return _unassign_role(project, queryset, kwargs['request'], TaskAssignment.Role.REVIEWER, 'reviewers')


def _assignees_form(user, project, field_name, label, required):
    """Dialog form with a multi-select of organization members."""
    users = _org_member_users(project)
    return [
        {
            'columnCount': 1,
            'fields': [
                {
                    'type': 'select',
                    'name': field_name,
                    'label': label,
                    'options': [
                        {'value': str(member.id), 'label': member.get_full_name() or member.username or member.email}
                        for member in users
                    ],
                    'multiple': True,
                    'searchable': True,
                    'required': required,
                }
            ],
        }
    ]


def assign_annotators_form(user, project):
    return _assignees_form(user, project, 'annotators', 'Annotators', required=True)


def delete_annotators_form(user, project):
    return _assignees_form(user, project, 'annotators', 'Annotators (empty = all)', required=False)


def assign_reviewers_form(user, project):
    return _assignees_form(user, project, 'reviewers', 'Reviewers', required=True)


def delete_reviewers_form(user, project):
    return _assignees_form(user, project, 'reviewers', 'Reviewers (empty = all)', required=False)


actions: list[DataManagerAction] = [
    {
        'entry_point': assign_annotators,
        'permission': ASSIGN_PERMISSION,
        'title': 'Assign Annotators',
        'order': 92,
        'dialog': {
            'title': 'Assign Annotators',
            'text': 'Assign the selected tasks to the chosen annotators. '
            'Annotators can only view and label tasks assigned to them.',
            'type': 'confirm',
            'form': assign_annotators_form,
        },
    },
    {
        'entry_point': delete_annotators,
        'permission': ASSIGN_PERMISSION,
        'title': 'Unassign Annotators',
        'order': 93,
        'dialog': {
            'title': 'Unassign Annotators',
            'text': 'Remove annotator assignments from the selected tasks. '
            'Leave the user list empty to remove all annotator assignments.',
            'type': 'confirm',
            'form': delete_annotators_form,
        },
    },
    {
        'entry_point': assign_reviewers,
        'permission': ASSIGN_PERMISSION,
        'title': 'Assign Reviewers',
        'order': 96,
        'dialog': {
            'title': 'Assign Reviewers',
            'text': 'Assign the selected tasks to the chosen reviewers.',
            'type': 'confirm',
            'form': assign_reviewers_form,
        },
    },
    {
        'entry_point': delete_reviewers,
        'permission': ASSIGN_PERMISSION,
        'title': 'Unassign Reviewers',
        'order': 97,
        'dialog': {
            'title': 'Unassign Reviewers',
            'text': 'Remove reviewer assignments from the selected tasks. '
            'Leave the user list empty to remove all reviewer assignments.',
            'type': 'confirm',
            'form': delete_reviewers_form,
        },
    },
]

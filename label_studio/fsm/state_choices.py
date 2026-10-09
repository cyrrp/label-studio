"""
FSM state choices registry system.

This module provides the infrastructure for registering and managing
state choices for different entity types in the FSM framework.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from fsm.registry import register_state_choices

"""
Core state choice enums for Label Studio entities.
These enums define the essential states for core Label Studio entities.
"""


@register_state_choices('task')
class TaskStateChoices(models.TextChoices):
    """
    Core task states for basic Label Studio workflow.
    Simplified states covering the essential task lifecycle:
    - Creation and assignment
    - Annotation work
    - Completion
    """

    # Initial State
    CREATED = 'CREATED', _('Created')

    # Work States
    IN_PROGRESS = 'IN_PROGRESS', _('In Progress')

    # Terminal State
    COMPLETED = 'COMPLETED', _('Completed')


@register_state_choices('annotation')
class AnnotationStateChoices(models.TextChoices):
    """Annotation lifecycle states.

    CREATED is the initial/submitted state; ACCEPTED / REJECTED /
    FIXED_AND_ACCEPTED are reached through the review workflow
    (see tasks.api.AnnotationReviewListAPI and fsm/review_transitions.py).
    """

    CREATED = 'CREATED', _('Created')

    # Review outcomes
    ACCEPTED = 'ACCEPTED', _('Accepted')
    REJECTED = 'REJECTED', _('Rejected')
    FIXED_AND_ACCEPTED = 'FIXED_AND_ACCEPTED', _('Fixed and accepted')


@register_state_choices('project')
class ProjectStateChoices(models.TextChoices):
    """
    Core project states for basic Label Studio workflow.
    Simplified states covering the essential project lifecycle:
    - Setup and configuration
    - Active work
    - Completion
    """

    # Setup States
    CREATED = 'CREATED', _('Created')

    # Work States
    IN_PROGRESS = 'IN_PROGRESS', _('In Progress')

    # Terminal State
    COMPLETED = 'COMPLETED', _('Completed')

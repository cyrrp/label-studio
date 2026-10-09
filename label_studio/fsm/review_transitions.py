"""
FSM Transitions for the community annotation review workflow.

These transitions are NOT model-save driven (triggers_on_create=False,
triggers_on_update=False): they are invoked explicitly from the review API
(tasks.api.AnnotationReviewListAPI / AnnotationReviewAPI) via
StateManager.execute_transition() after the review record and
annotation.last_action have been persisted.

Each transition forces a state record so the full review history is kept even
when the resulting state doesn't change (e.g. reject -> reject).
"""

from typing import Any, Dict, Optional

from fsm.registry import register_state_transition
from fsm.state_choices import AnnotationStateChoices
from fsm.transitions import BaseTransition, TransitionContext


class _AnnotationReviewTransition(BaseTransition):
    """Shared bookkeeping for review transitions.

    `get_target_state` is overridden per result; `transition` stores the
    annotation/review identifiers in the state record's context_data.
    """

    def transition(self, context: TransitionContext) -> Dict[str, Any]:
        annotation = context.entity
        return {
            'task_id': annotation.task_id,
            'project_id': annotation.project_id,
            'completed_by_id': annotation.completed_by_id,
            'reviewed_by_id': context.current_user.id if context.current_user else None,
            **context.context_data,
        }


@register_state_transition(
    'annotation', 'annotation_accepted', triggers_on_create=False, triggers_on_update=False, force_state_record=True
)
class AnnotationAcceptedTransition(_AnnotationReviewTransition):
    """Annotation accepted by a reviewer."""

    def get_target_state(self, context: Optional[TransitionContext] = None) -> str:
        return AnnotationStateChoices.ACCEPTED

    def get_reason(self, context: TransitionContext) -> str:
        return 'Annotation accepted by reviewer'


@register_state_transition(
    'annotation', 'annotation_rejected', triggers_on_create=False, triggers_on_update=False, force_state_record=True
)
class AnnotationRejectedTransition(_AnnotationReviewTransition):
    """Annotation rejected by a reviewer; it re-enters the labeling queue for rework."""

    def get_target_state(self, context: Optional[TransitionContext] = None) -> str:
        return AnnotationStateChoices.REJECTED

    def get_reason(self, context: TransitionContext) -> str:
        return 'Annotation rejected by reviewer'


@register_state_transition(
    'annotation',
    'annotation_fixed_and_accepted',
    triggers_on_create=False,
    triggers_on_update=False,
    force_state_record=True,
)
class AnnotationFixedAndAcceptedTransition(_AnnotationReviewTransition):
    """Reviewer corrected the annotation result and accepted it in one action."""

    def get_target_state(self, context: Optional[TransitionContext] = None) -> str:
        return AnnotationStateChoices.FIXED_AND_ACCEPTED

    def get_reason(self, context: TransitionContext) -> str:
        return 'Annotation fixed and accepted by reviewer'


@register_state_transition(
    'annotation',
    'annotation_review_deleted',
    triggers_on_create=False,
    triggers_on_update=False,
    force_state_record=True,
)
class AnnotationReviewDeletedTransition(_AnnotationReviewTransition):
    """A review record was deleted; the annotation returns to the unreviewed state."""

    def get_target_state(self, context: Optional[TransitionContext] = None) -> str:
        return AnnotationStateChoices.CREATED

    def get_reason(self, context: TransitionContext) -> str:
        return 'Annotation review deleted'

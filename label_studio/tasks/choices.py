from django.db import models
from django.utils.translation import gettext_lazy as _


class ActionType(models.TextChoices):
    CREATED_FROM_PREDICTION = 'prediction', _('Created from prediction')
    PROPAGATED_ANNOTATION = 'propagated_annotation', _('Created from another annotation')
    IMPORTED = 'imported', _('Imported')
    SUBMITTED = 'submitted', _('Submitted')
    UPDATED = 'updated', _('Updated')
    SKIPPED = 'skipped', _('Skipped')
    ACCEPTED = 'accepted', _('Accepted')
    REJECTED = 'rejected', _('Rejected')
    FIXED_AND_ACCEPTED = 'fixed_and_accepted', _('Fixed and accepted')
    DELETED_REVIEW = 'deleted_review', _('Deleted review')


class ReviewResult(models.TextChoices):
    """Possible results of an AnnotationReview.

    Values intentionally match ActionType so that a review result can be
    written straight into Annotation.last_action.
    """

    ACCEPTED = 'accepted', _('Accepted')
    REJECTED = 'rejected', _('Rejected')
    FIXED_AND_ACCEPTED = 'fixed_and_accepted', _('Fixed and accepted')

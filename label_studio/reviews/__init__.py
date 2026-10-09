"""Compatibility package for the LSE ``reviews`` app.

Enterprise code paths (e.g. ``data_export.mixins``) do
``from reviews.models import AnnotationReview``. In Label Studio Community the
model lives in ``tasks.models``; this package re-exports it so those imports keep
working without a separate Django app (no INSTALLED_APPS entry needed).
"""

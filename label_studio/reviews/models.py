"""Re-export of the community AnnotationReview model under the LSE module path.

In LSE ``reviews`` is a standalone Django app; in LSO the review model lives in
``tasks.models.AnnotationReview``. Keeping the import path working lets shared
code (data_export prefetch, io_storages expand) work in both editions.
"""

from tasks.models import AnnotationReview  # noqa: F401

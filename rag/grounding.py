"""Decide whether the documentation KB actually covers the question."""
from django.conf import settings


def grounding(doc_chunks, threshold=None):
    """Return (grounded, top_score). Grounded iff the best doc cosine >= threshold."""
    threshold = settings.GROUNDING_THRESHOLD if threshold is None else threshold
    top = max((c["score"] for c in doc_chunks), default=0.0)
    return top >= threshold, round(top, 4)

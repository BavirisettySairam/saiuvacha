"""
Gate 2: Confidence threshold check.

After Qdrant returns results, check the top similarity score.
Returns a confidence level: 'high', 'low', or 'none'.
"""

from django.conf import settings


def check(chunks: list[dict]) -> str:
    """
    Returns:
        'none' → top score below CONFIDENCE_THRESHOLD → no LLM call, return fallback
        'low'  → top score between CONFIDENCE_THRESHOLD and CONFIDENCE_HIGH
                 → proceed but instruct Claude to be honest about limitations
        'high' → top score above CONFIDENCE_HIGH → proceed normally
    """
    if not chunks:
        return 'none'

    top_score = chunks[0]['score']
    low = settings.CONFIDENCE_THRESHOLD     # default 0.42
    high = settings.CONFIDENCE_HIGH         # default 0.55

    if top_score < low:
        return 'none'
    if top_score < high:
        return 'low'
    return 'high'

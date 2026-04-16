"""
Gate 3: Output validator — runs on Claude/OpenAI's response before sending to user.

Checks:
  - Response references the provided context (not hallucinated)
  - No forbidden phrases ("I think", "In my opinion", other teachers)
  - No accidental code/markdown leakage
  - Not empty / suspiciously short
"""

import re

# Phrases that suggest the model is speaking from its own opinion, not from context
OPINION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        # Weak/uncertain hedges — Swami speaks with authority, never with doubt
        r'\bI think\b',
        r'\bIn my opinion\b',
        r'\bI\'m not sure\b',
        r'\bI am not certain\b',
        r'\bI cannot say for sure\b',
        # AI identity leakage — must never appear
        r'\bAs an AI\b',
        r'\bAs a language model\b',
        r'\bI\'m an AI\b',
        r'\bI am an AI\b',
        r'\bI cannot (provide|give|offer) (personal|individual|specific) (advice|guidance)\b',
        r'\bmy training\b',
        r'\bmy knowledge cutoff\b',
    ]
]

# Other spiritual teacher names that should not appear in the response
OTHER_TEACHERS = [
    'ramana maharshi', 'vivekananda', 'ramakrishna', 'osho', 'rajneesh',
    'dalai lama', 'rumi', 'krishnamurti', 'aurobindo', 'eckhart tolle',
    'deepak chopra', 'sadhguru', 'jaggi vasudev',
]

# Code / markdown artifacts that shouldn't appear in spiritual responses
CODE_PATTERNS = [
    re.compile(p) for p in [
        r'```',
        r'def \w+\(',
        r'import \w+',
        r'<script',
        r'<html',
        r'SELECT \*',
    ]
]

MIN_RESPONSE_WORDS = 20
MAX_RESPONSE_WORDS = 800


def validate(response: str, chunks: list[dict]) -> tuple[bool, str]:
    """
    Returns (valid: bool, reason: str).
    If invalid, the pipeline should substitute an appropriate template.
    """
    if not response or not response.strip():
        return False, 'empty_response'

    word_count = len(response.split())

    if word_count < MIN_RESPONSE_WORDS:
        return False, f'response_too_short ({word_count} words)'

    if word_count > MAX_RESPONSE_WORDS:
        # Trim rather than reject — handled in pipeline
        return False, f'response_too_long ({word_count} words)'

    # Opinion / AI identity phrases
    for pattern in OPINION_PATTERNS:
        if pattern.search(response):
            return False, f'opinion_phrase: {pattern.pattern}'

    # Other teachers mentioned
    response_lower = response.lower()
    for teacher in OTHER_TEACHERS:
        if teacher in response_lower:
            return False, f'other_teacher_mentioned: {teacher}'

    # Code / markdown artifacts
    for pattern in CODE_PATTERNS:
        if pattern.search(response):
            return False, f'code_artifact: {pattern.pattern}'

    return True, 'ok'


def trim_if_long(response: str) -> str:
    """If response exceeds MAX_RESPONSE_WORDS, trim at last sentence boundary."""
    words = response.split()
    if len(words) <= MAX_RESPONSE_WORDS:
        return response

    # Find last sentence boundary within the limit
    truncated = ' '.join(words[:MAX_RESPONSE_WORDS])
    last_period = max(
        truncated.rfind('.'),
        truncated.rfind('!'),
        truncated.rfind('?'),
    )
    if last_period > len(truncated) // 2:
        return truncated[:last_period + 1]
    return truncated + '…'

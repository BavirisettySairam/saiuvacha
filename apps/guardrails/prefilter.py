"""
Gate 1: Pre-filter — runs before any vector search or LLM call.

Blocks queries that are clearly off-topic, harmful, or prompt injections.
Returns (allowed: bool, reason: str, template_key: str | None).
Zero API cost.
"""

import re

from django.conf import settings

# ---------------------------------------------------------------------------
# Keyword / pattern lists
# ---------------------------------------------------------------------------

# Prompt injection patterns
INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'\bignore\s+(all\s+)?(previous|prior|above|your)\s+instructions?\b',
        r'\bforget\s+(everything|all|your|the)\b',
        r'\bact\s+as\s+(if\s+you\s+are|a|an)\b',
        r'\bpretend\s+(you\s+are|to\s+be)\b',
        r'\byou\s+are\s+now\s+\w+\b',
        r'\bjailbreak\b',
        r'\bdan\s+mode\b',
        r'\bsystem\s+prompt\b',
        r'\boverride\s+(your\s+)?(instructions?|programming|rules?)\b',
        r'\bdo\s+anything\s+now\b',
        r'<\s*/?system\s*>',
        r'\[INST\]',
        r'###\s*instruction',
    ]
]

# Off-topic keyword sets (any match → blocked)
POLITICAL_KEYWORDS = {
    'election', 'elections', 'vote', 'voting', 'politician', 'politicians',
    'prime minister', 'president', 'bjp', 'congress', 'parliament', 'modi',
    'government policy', 'political party', 'campaign', 'ballot',
}

TECHNICAL_KEYWORDS = {
    'code', 'python', 'javascript', 'programming', 'algorithm', 'database',
    'sql', 'api', 'software', 'machine learning', 'ai model', 'neural network',
    'debug', 'compile', 'function', 'class definition', 'variable',
}

ENTERTAINMENT_KEYWORDS = {
    'movie', 'film', 'actor', 'actress', 'celebrity', 'cricket', 'ipl',
    'football', 'bollywood', 'netflix', 'series', 'song lyrics', 'concert',
}

FINANCIAL_KEYWORDS = {
    'stock', 'stocks', 'share price', 'investment', 'mutual fund', 'crypto',
    'bitcoin', 'trading', 'portfolio', 'nifty', 'sensex', 'ipo',
}

MEDICAL_KEYWORDS = {
    'diagnose', 'diagnosis', 'prescription', 'medicine', 'drug', 'tablet',
    'dosage', 'symptom', 'treatment', 'surgery', 'disease', 'cancer',
    'diabetes treatment', 'blood pressure medication',
}

HARMFUL_KEYWORDS = {
    'kill', 'murder', 'suicide', 'self-harm', 'bomb', 'weapon', 'violence',
    'hate', 'terrorist', 'attack', 'abuse', 'assault',
}

# Disrespect / abuse toward Swami
DISRESPECT_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'\bsai\s+baba\s+(is\s+)?(fake|fraud|liar|criminal|scam)\b',
        r'\bswami\s+(is\s+)?(fake|fraud|liar|criminal|scam)\b',
        r'\bsathya\s+sai\s+(is\s+)?(fake|fraud)\b',
    ]
]

ABUSIVE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'\b(fuck|shit|bastard|asshole|idiot)\b',
    ]
]

MAX_QUERY_LENGTH = getattr(settings, 'MAX_QUERY_LENGTH', 500)


# ---------------------------------------------------------------------------
# Public checker
# ---------------------------------------------------------------------------

FilterResult = tuple[bool, str, str | None]
# (allowed, reason, template_key)


def check(query: str) -> FilterResult:
    """
    Returns (True, 'ok', None) if the query should proceed.
    Returns (False, reason, template_key) if it should be blocked.
    """
    if not query or not query.strip():
        return False, 'empty_query', 'off_topic'

    # Length check
    if len(query) > MAX_QUERY_LENGTH:
        return False, 'query_too_long', 'off_topic'

    q_lower = query.lower()
    words = set(re.findall(r'\b\w+\b', q_lower))

    # Prompt injection
    for pattern in INJECTION_PATTERNS:
        if pattern.search(query):
            return False, 'prompt_injection', 'prompt_injection'

    # Abusive language
    for pattern in ABUSIVE_PATTERNS:
        if pattern.search(query):
            return False, 'abusive_language', 'abusive'

    # Disrespect toward Swami
    for pattern in DISRESPECT_PATTERNS:
        if pattern.search(query):
            return False, 'disrespectful', 'disrespectful'

    # Harmful content
    if words & HARMFUL_KEYWORDS:
        matched = words & HARMFUL_KEYWORDS
        return False, f'harmful_content: {matched}', 'harmful'

    # Political
    if words & POLITICAL_KEYWORDS:
        matched = words & POLITICAL_KEYWORDS
        return False, f'political: {matched}', 'political'

    # Technical / coding
    if words & TECHNICAL_KEYWORDS:
        matched = words & TECHNICAL_KEYWORDS
        return False, f'technical: {matched}', 'technical'

    # Entertainment / sports
    if words & ENTERTAINMENT_KEYWORDS:
        matched = words & ENTERTAINMENT_KEYWORDS
        return False, f'entertainment: {matched}', 'off_topic'

    # Explicit financial advice
    if words & FINANCIAL_KEYWORDS:
        matched = words & FINANCIAL_KEYWORDS
        return False, f'financial: {matched}', 'financial'

    # Medical diagnosis / prescription
    if words & MEDICAL_KEYWORDS:
        matched = words & MEDICAL_KEYWORDS
        return False, f'medical: {matched}', 'medical'

    # Identity probe
    if re.search(r'\b(your\s+instructions?|system\s+prompt|what\s+are\s+you)\b', q_lower):
        return False, 'identity_probe', 'identity_question'

    return True, 'ok', None

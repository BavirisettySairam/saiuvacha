"""
Redis response cache — saves LLM API calls on repeated queries.

Key  : SHA-256 of normalised query (lowercase, whitespace-collapsed)
TTL  : settings.CACHE_TTL (default 7 days)

Fails silently if Redis is unavailable — the pipeline continues without caching.
"""

import hashlib
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_client = None
CACHE_PREFIX = 'sai_uvacha:response:'
_DEFAULT_TTL = 60 * 60 * 24 * 7  # 7 days


def _get_client():
    global _client
    if _client is None:
        import redis
        url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0')
        _client = redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    return _client


def _key(query: str) -> str:
    normalised = ' '.join(query.lower().split())
    digest = hashlib.sha256(normalised.encode()).hexdigest()[:20]
    return f'{CACHE_PREFIX}{digest}'


def get(query: str) -> str | None:
    """
    Return a cached response string, or None on miss / Redis unavailable.
    """
    try:
        value = _get_client().get(_key(query))
        if value:
            logger.info('Cache HIT | query=%r', query[:60])
            return json.loads(value)
    except Exception as exc:
        logger.debug('Cache get skipped (%s)', exc)
    return None


def store(query: str, response: str) -> None:
    """
    Persist a response string with TTL. Silently skips on Redis unavailable.
    """
    try:
        ttl = getattr(settings, 'CACHE_TTL', _DEFAULT_TTL)
        _get_client().setex(_key(query), ttl, json.dumps(response))
        logger.info('Cache STORE | query=%r', query[:60])
    except Exception as exc:
        logger.debug('Cache store skipped (%s)', exc)


def invalidate(query: str) -> None:
    """Remove a specific query from cache (useful for admin overrides)."""
    try:
        _get_client().delete(_key(query))
    except Exception:
        pass

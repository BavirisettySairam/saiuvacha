"""
Full 3-gate RAG pipeline — single entry point for the chat view.

Usage:
    from apps.rag.pipeline import ask, stream_ask

    # Non-streaming (returns full response string):
    result = ask("How can I find inner peace?")
    print(result['response'])

    # Streaming (yields tokens one by one):
    for token in stream_ask("How can I find inner peace?"):
        print(token, end='', flush=True)
"""

import logging
from typing import Iterator

from apps.guardrails import confidence as gate2
from apps.guardrails import prefilter as gate1
from apps.guardrails import validator as gate3
from apps.guardrails.templates import get_template
from apps.rag import cache as response_cache
from apps.rag import composer, llm, retriever

logger = logging.getLogger(__name__)

TOP_K = 5   # number of chunks to retrieve


# ---------------------------------------------------------------------------
# Result schema
# ---------------------------------------------------------------------------

def _result(
    response: str,
    blocked: bool = False,
    block_reason: str = '',
    chunks: list | None = None,
    confidence: str = '',
    gate3_valid: bool = True,
) -> dict:
    return {
        'response': response,
        'blocked': blocked,
        'block_reason': block_reason,
        'chunks': chunks or [],
        'confidence': confidence,
        'gate3_valid': gate3_valid,
    }


# ---------------------------------------------------------------------------
# Non-streaming
# ---------------------------------------------------------------------------

def ask(query: str, language: str = 'en') -> dict:
    """
    Run the full 3-gate pipeline and return a result dict.

    result keys:
        response     — the text to show the user
        blocked      — True if blocked by Gate 1
        block_reason — why it was blocked (for logging)
        chunks       — retrieved discourse chunks
        confidence   — 'high' | 'low' | 'none'
        gate3_valid  — whether Gate 3 validation passed
    """
    # --- Gate 1: Pre-filter ---
    allowed, reason, template_key = gate1.check(query)
    if not allowed:
        logger.info('Gate1 blocked | reason=%s | query=%r', reason, query[:80])
        return _result(
            response=get_template(template_key or 'off_topic'),
            blocked=True,
            block_reason=reason,
        )

    # --- Cache check (after Gate 1 — only cache valid spiritual queries) ---
    cached = response_cache.get(query)
    if cached:
        return _result(response=cached, confidence='cached')

    # --- Retrieve ---
    chunks = retriever.retrieve(query, top_k=TOP_K)

    # --- Gate 2: Confidence threshold ---
    # 'none' no longer hard-blocks — Swami responds from general wisdom.
    # Gate 2 only controls HOW Swami responds, not WHETHER.
    confidence = gate2.check(chunks)
    if confidence == 'none':
        logger.info('Gate2 none confidence | top_score=%s | query=%r — general wisdom mode',
                    chunks[0]['score'] if chunks else 0, query[:80])

    # --- Build prompt ---
    system, user_message = composer.compose(
        query=query,
        chunks=chunks,
        language=language,
        confidence_level=confidence,
    )

    # --- LLM call ---
    response_text = llm.get_response(system, user_message)

    # --- Gate 3: Output validation ---
    valid, gate3_reason = gate3.validate(response_text, chunks)
    if not valid:
        if 'too_long' in gate3_reason:
            response_text = gate3.trim_if_long(response_text)
            valid = True
        else:
            logger.warning('Gate3 failed | reason=%s | query=%r', gate3_reason, query[:80])
            response_text = get_template('off_topic')

    logger.info(
        'Pipeline ok | confidence=%s | gate3=%s | chunks=%d | query=%r',
        confidence, valid, len(chunks), query[:80],
    )

    # --- Cache store (only successful, validated responses) ---
    if valid:
        response_cache.store(query, response_text)

    return _result(
        response=response_text,
        chunks=chunks,
        confidence=confidence,
        gate3_valid=valid,
    )


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

def stream_ask(query: str, language: str = 'en') -> Iterator[str]:
    """
    Streaming version — yields tokens as they arrive.
    Gate 1 and Gate 2 run synchronously first.
    Gate 3 cannot run on streaming output (checked post-hoc in chat view).

    On block, yields the template response in one chunk.
    """
    # Gate 1
    allowed, reason, template_key = gate1.check(query)
    if not allowed:
        logger.info('Gate1 blocked | reason=%s | query=%r', reason, query[:80])
        yield get_template(template_key or 'off_topic')
        return

    # Cache check — yield cached response immediately, skip LLM entirely
    cached = response_cache.get(query)
    if cached:
        yield cached
        return

    # Retrieve
    chunks = retriever.retrieve(query, top_k=TOP_K)

    # Gate 2 — 'none' no longer hard-blocks
    confidence = gate2.check(chunks)
    if confidence == 'none':
        logger.info('Gate2 none confidence | query=%r — general wisdom mode', query[:80])

    # Build prompt
    system, user_message = composer.compose(
        query=query,
        chunks=chunks,
        language=language,
        confidence_level=confidence,
    )

    # Stream LLM response
    yield from llm.stream_response(system, user_message)

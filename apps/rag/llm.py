"""
LLM caller — provider-agnostic interface.

Currently uses OpenAI (gpt-4o-mini).
To switch to Claude, set LLM_PROVIDER=claude in .env and add ANTHROPIC_API_KEY.

Both providers expose the same interface:
    stream_response(system, user_message) → Iterator[str]   (token by token)
    get_response(system, user_message)    → str             (full response)
"""

from django.conf import settings

# Model config — change these to switch providers
OPENAI_MODEL = 'gpt-4o-mini'
CLAUDE_MODEL = 'claude-sonnet-4-6'
MAX_TOKENS = 1024
TEMPERATURE = 0.8  # warm, varied — not robotic, not erratic


def _provider() -> str:
    return getattr(settings, 'LLM_PROVIDER', 'openai').lower()


# ---------------------------------------------------------------------------
# OpenAI backend
# ---------------------------------------------------------------------------

def _openai_stream(system: str, user_message: str):
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    stream = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user_message},
        ],
        max_tokens=MAX_TOKENS,
        temperature=0.7,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def _openai_complete(system: str, user_message: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user_message},
        ],
        max_tokens=MAX_TOKENS,
        temperature=0.7,
        stream=False,
    )
    return response.choices[0].message.content or ''


# ---------------------------------------------------------------------------
# Claude backend (ready — just needs ANTHROPIC_API_KEY in .env)
# ---------------------------------------------------------------------------

def _claude_stream(system: str, user_message: str):
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=system,
        messages=[{'role': 'user', 'content': user_message}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def _claude_complete(system: str, user_message: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=system,
        messages=[{'role': 'user', 'content': user_message}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def stream_response(system: str, user_message: str):
    """Yield response tokens one by one. Use for SSE streaming to browser."""
    provider = _provider()
    if provider == 'claude':
        yield from _claude_stream(system, user_message)
    else:
        yield from _openai_stream(system, user_message)


def get_response(system: str, user_message: str) -> str:
    """Return full response as a string. Use for testing and guardrail checks."""
    provider = _provider()
    if provider == 'claude':
        return _claude_complete(system, user_message)
    else:
        return _openai_complete(system, user_message)

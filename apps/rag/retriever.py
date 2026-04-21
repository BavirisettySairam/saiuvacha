"""
Retriever: embed a query and fetch top-k chunks from Qdrant.

Uses HyDE (Hypothetical Document Embeddings):
  Instead of embedding the raw query, GPT-4o-mini first generates a short
  hypothetical Sai Baba discourse passage about the topic. That passage is
  embedded — its vector sits much closer to actual discourse chunks than a
  colloquial user query would.

Falls back to direct query embedding if HyDE generation fails.
Also applies glossary expansion for Sanskrit/Telugu term coverage.
"""

import json
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

GLOSSARY_PATH = Path(__file__).resolve().parent.parent.parent / 'config' / 'glossary.json'
_glossary: dict | None = None

# HyDE generation prompt — tells GPT-4o-mini exactly what to produce
_HYDE_SYSTEM = (
    "You are generating a short excerpt from a discourse by Bhagawan Sri Sathya Sai Baba. "
    "Write 80–120 words in Swami's voice: first person, loving, direct, spiritually rich. "
    "Use Sanskrit terms naturally (e.g. Krodha, Shanthi, Atma, Dharma, Prema). "
    "Use analogies from nature or daily life as Swami did. "
    "Do NOT invent specific stories or events — speak in Swami's general teaching style. "
    "Write in English only, regardless of the topic language. "
    "Output only the passage — no titles, no labels, no extra text."
)


# ---------------------------------------------------------------------------
# Glossary expansion
# ---------------------------------------------------------------------------

def _load_glossary() -> dict:
    global _glossary
    if _glossary is None:
        if GLOSSARY_PATH.exists():
            _glossary = json.loads(GLOSSARY_PATH.read_text())['terms']
        else:
            _glossary = {}
    return _glossary


def expand_query(query: str) -> str:
    """Append relevant Sanskrit/Telugu synonyms to improve embedding coverage."""
    glossary = _load_glossary()
    query_lower = query.lower()
    extra = []

    for key, synonyms in glossary.items():
        if key in query_lower:
            for s in synonyms:
                if s.lower() not in query_lower and s not in extra:
                    extra.append(s)

    if extra:
        return query + ' ' + ' '.join(extra[:6])
    return query


# ---------------------------------------------------------------------------
# HyDE: hypothetical passage generation
# ---------------------------------------------------------------------------

def generate_hypothetical_passage(query: str) -> str:
    """
    Use GPT-4o-mini to generate a short hypothetical Sai Baba discourse
    passage about the query topic. The passage is then embedded instead of
    the raw query — its vector sits naturally close to real discourse chunks.

    Returns the passage, or the original query on failure.
    """
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': _HYDE_SYSTEM},
                {'role': 'user',   'content': f'Topic: {query}'},
            ],
            max_tokens=180,
            temperature=0.3,
        )
        passage = (response.choices[0].message.content or '').strip()
        if passage:
            logger.debug('HyDE passage (%d words): %s...', len(passage.split()), passage[:80])
            return passage
    except Exception as exc:
        logger.warning('HyDE generation failed (%s) — falling back to raw query', exc)

    return query


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_query(text: str) -> list[float]:
    """Embed a text string using OpenAI text-embedding-3-small."""
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.embeddings.create(
        model='text-embedding-3-small',
        input=text,
    )
    return response.data[0].embedding


# ---------------------------------------------------------------------------
# Main retrieval function
# ---------------------------------------------------------------------------

def retrieve(query: str, top_k: int = 8) -> list[dict]:
    """
    Full retrieval pipeline:
      1. Glossary-expand the query (Sanskrit/Telugu coverage)
      2. Generate a hypothetical discourse passage via HyDE (GPT-4o-mini)
      3. Embed the passage (text-embedding-3-small)
      4. Search Qdrant, return top-k chunks

    Each returned chunk dict has:
        text, score, title, date, event, place, year,
        citeable, section_type, chunk_index, source_file
    """
    from qdrant_client import QdrantClient

    # Step 1: glossary expansion (appended to query for HyDE context)
    expanded_query = expand_query(query)

    # Step 2: HyDE — generate hypothetical passage in Swami's style
    hyde_passage = generate_hypothetical_passage(expanded_query)

    # Step 3: embed the hypothetical passage
    vector = embed_query(hyde_passage)

    # Step 4: search Qdrant
    client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=60,
    )

    response = client.query_points(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        query=vector,
        limit=top_k,
        with_payload=True,
    )

    chunks = []
    for point in response.points:
        p = point.payload or {}
        chunks.append({
            'text':         p.get('text', ''),
            'score':        round(point.score, 4),
            'title':        p.get('title', ''),
            'date':         p.get('date', ''),
            'event':        p.get('event', ''),
            'place':        p.get('place', ''),
            'year':         p.get('year'),
            'citeable':     p.get('citeable', True),
            'section_type': p.get('section_type', 'teaching'),
            'chunk_index':  p.get('chunk_index', 0),
            'source_file':  p.get('source_file', ''),
        })

    return chunks

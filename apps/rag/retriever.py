"""
Retriever: embed a query and fetch top-k chunks from Qdrant.
Also applies glossary expansion to improve recall.
"""

import json
from pathlib import Path

from django.conf import settings

GLOSSARY_PATH = Path(__file__).resolve().parent.parent.parent / 'config' / 'glossary.json'
_glossary: dict | None = None


def _load_glossary() -> dict:
    global _glossary
    if _glossary is None:
        if GLOSSARY_PATH.exists():
            _glossary = json.loads(GLOSSARY_PATH.read_text())['terms']
        else:
            _glossary = {}
    return _glossary


def expand_query(query: str) -> str:
    """
    Append relevant Sanskrit/Telugu synonyms to the query so the embedding
    covers both English and Swami's vocabulary.

    E.g. "meditation" → "meditation dhyana contemplation sadhana"
    """
    glossary = _load_glossary()
    query_lower = query.lower()
    extra = []

    for key, synonyms in glossary.items():
        if key in query_lower:
            # Add synonyms not already in the query
            for s in synonyms:
                if s.lower() not in query_lower and s not in extra:
                    extra.append(s)

    if extra:
        return query + ' ' + ' '.join(extra[:6])   # cap at 6 extra terms
    return query


def embed_query(query: str) -> list[float]:
    """Embed a single query string using OpenAI text-embedding-3-small."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.embeddings.create(
        model='text-embedding-3-small',
        input=query,
    )
    return response.data[0].embedding


def retrieve(query: str, top_k: int = 5) -> list[dict]:
    """
    Expand query, embed it, search Qdrant, return top-k chunks as dicts.

    Each chunk dict has:
        text, score, title, date, event, place, year,
        citeable, section_type, chunk_index, source_file
    """
    from qdrant_client import QdrantClient

    expanded = expand_query(query)
    vector = embed_query(expanded)

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
            'text': p.get('text', ''),
            'score': round(point.score, 4),
            'title': p.get('title', ''),
            'date': p.get('date', ''),
            'event': p.get('event', ''),
            'place': p.get('place', ''),
            'year': p.get('year'),
            'citeable': p.get('citeable', True),
            'section_type': p.get('section_type', 'teaching'),
            'chunk_index': p.get('chunk_index', 0),
            'source_file': p.get('source_file', ''),
        })

    return chunks

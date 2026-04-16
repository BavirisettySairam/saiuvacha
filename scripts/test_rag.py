"""
Test retrieval quality after ingestion.

Usage:
    python scripts/test_rag.py
    python scripts/test_rag.py --query "How to find inner peace?"
    python scripts/test_rag.py --top 5
"""

import argparse
import os
import sys
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
django.setup()

from django.conf import settings

TEST_QUERIES = [
    "How can I find inner peace?",
    "What is the purpose of human life?",
    "How to control anger and bad thoughts?",
    "What does Swami say about meditation?",
    "How to develop love for God?",
    "What is true education according to Swami?",
    "How to serve others selflessly?",
    "What is the meaning of Sathya Dharma Shanthi Prema Ahimsa?",
    "How to overcome ego?",
    "What does Swami say about the unity of religions?",
]


def search(query: str, top_k: int = 3) -> list[dict]:
    from openai import OpenAI
    from qdrant_client import QdrantClient

    openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    qdrant_client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)

    response = openai_client.embeddings.create(
        model='text-embedding-3-small',
        input=query,
    )
    query_vector = response.data[0].embedding

    response = qdrant_client.query_points(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    )
    results = response.points

    return [
        {
            'score': round(r.score, 4),
            'title': r.payload.get('title', ''),
            'date': r.payload.get('date', ''),
            'event': r.payload.get('event', ''),
            'place': r.payload.get('place', ''),
            'citeable': r.payload.get('citeable', True),
            'section_type': r.payload.get('section_type', ''),
            'text': r.payload.get('text', '')[:300] + '...',
        }
        for r in results
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--query', type=str, default=None)
    parser.add_argument('--top', type=int, default=3)
    args = parser.parse_args()

    queries = [args.query] if args.query else TEST_QUERIES

    for query in queries:
        print(f'\n{"="*60}')
        print(f'Query: {query}')
        print('='*60)

        results = search(query, top_k=args.top)

        for i, r in enumerate(results, 1):
            print(f'\n  [{i}] Score: {r["score"]}  |  {r["section_type"].upper()}')
            if r['citeable']:
                print(f'      {r["title"]} — {r["event"]}, {r["place"]} ({r["date"]})')
            else:
                print(f'      [non-citeable discourse]')
            print(f'      {r["text"]}')

        if results:
            top_score = results[0]['score']
            low = settings.CONFIDENCE_THRESHOLD
            high = settings.CONFIDENCE_HIGH
            if top_score >= high:
                status = 'PASS (high confidence)'
            elif top_score >= low:
                status = 'PASS (low confidence — instruct caution)'
            else:
                status = 'BELOW THRESHOLD — no relevant teaching found'
            print(f'\n  Top score: {top_score} (low={low}, high={high}) → {status}')


if __name__ == '__main__':
    main()

"""Compare retrieval scores: raw query vs HyDE passage."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
import django; django.setup()

from apps.rag.retriever import (
    expand_query, embed_query, generate_hypothetical_passage, retrieve
)
from qdrant_client import QdrantClient
from django.conf import settings

client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, timeout=60)

def search_with_text(text, top_k=3):
    vec = embed_query(text)
    res = client.query_points(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        query=vec, limit=top_k, with_payload=False,
    )
    return [round(p.score, 4) for p in res.points]

queries = [
    "How to control anger?",
    "What is the purpose of life?",
    "How to find peace of mind?",
    "How to overcome ego and pride?",
    "How to develop love for God?",
]

print(f"{'Query':<40} {'Raw':>18}  {'HyDE':>18}  {'Improvement'}")
print("-" * 90)

for q in queries:
    expanded = expand_query(q)
    raw_scores   = search_with_text(expanded)
    passage      = generate_hypothetical_passage(q)
    hyde_scores  = search_with_text(passage)

    raw_top  = max(raw_scores)
    hyde_top = max(hyde_scores)
    delta    = hyde_top - raw_top
    sign     = "+" if delta >= 0 else ""

    print(f"{q:<40} {str(raw_scores):>18}  {str(hyde_scores):>18}  {sign}{delta:.4f}")
    print(f"  HyDE: {passage[:90]}...")
    print()

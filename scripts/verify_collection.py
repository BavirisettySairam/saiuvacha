"""Quick verification of Qdrant collection after re-ingestion."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
import django; django.setup()

from django.conf import settings
from qdrant_client import QdrantClient

client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, timeout=60)
info = client.get_collection(settings.QDRANT_COLLECTION_NAME)

print(f"Collection : {settings.QDRANT_COLLECTION_NAME}")
print(f"Points     : {info.points_count}")
print(f"Status     : {info.status}")

# Sample a retrieval to confirm scores improved
from apps.rag.retriever import retrieve

test_queries = [
    "How to control anger?",
    "What is the purpose of life?",
    "How to find peace of mind?",
    "How to overcome ego?",
]

print("\nRetrieval quality check:")
for q in test_queries:
    chunks = retrieve(q, top_k=3)
    scores = [c['score'] for c in chunks]
    types  = [c['section_type'] for c in chunks]
    print(f"  '{q[:40]}' → scores {scores}  types={types}")

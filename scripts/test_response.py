import django, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
django.setup()

from apps.rag.pipeline import ask

queries = [
    ("How can I control my anger?", "en"),
    ("How do I find peace of mind?", "en"),
    ("What is the purpose of life?", "en"),
]

for query, lang in queries:
    print("=" * 60)
    print(f"Q: {query}")
    print("=" * 60)
    result = ask(query, language=lang)
    print(f"Confidence: {result['confidence']} | Chunks: {len(result['chunks'])}")
    if result['chunks']:
        print(f"Top score: {result['chunks'][0]['score']}")
    print()
    print(result['response'])
    print()

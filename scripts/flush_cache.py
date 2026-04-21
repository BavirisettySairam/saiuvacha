import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
import django; django.setup()

from apps.rag.cache import flush_all
n = flush_all()
print(f'Deleted {n} cached responses.')

import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
import django; django.setup()

from pathlib import Path
from scripts.ingest import (
    clean_text, parse_filename, group_into_sections,
    sections_to_chunks, DISCOURSES_DIR,
)

all_files = sorted(DISCOURSES_DIR.rglob('*.md'))
all_files = [f for f in all_files if f.name != '.gitkeep' and f.stat().st_size > 500]

print("Files with chunks > 500 words:\n")
for filepath in all_files:
    text = filepath.read_text(encoding='utf-8')
    text = clean_text(text)
    if not text.strip():
        continue
    metadata = parse_filename(filepath)
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
    sections = group_into_sections(paragraphs)
    chunks = sections_to_chunks(sections, metadata)
    bad = [(i, c) for i, c in enumerate(chunks) if c['metadata']['word_count'] > 500]
    if bad:
        print(f"\n{'='*60}")
        print(f"FILE: {filepath.name}")
        for idx, c in bad:
            wc = c['metadata']['word_count']
            stype = c['metadata']['section_type']
            print(f"  Chunk {idx}: {wc}w ({stype})")
            print(f"  Text preview: {c['text'][:200]}")
            print()

# Also find the single biggest paragraph across all files
print("\n\nLARGEST SINGLE PARAGRAPHS:")
biggest = []
for filepath in all_files:
    text = filepath.read_text(encoding='utf-8')
    text = clean_text(text)
    paras = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
    for p in paras:
        wc = len(p.split())
        if wc > 400:
            biggest.append((wc, filepath.name, p[:150]))

biggest.sort(reverse=True)
for wc, fname, preview in biggest[:10]:
    print(f"\n{wc}w — {fname}")
    print(f"  {preview}")

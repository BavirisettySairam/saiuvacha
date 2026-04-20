"""
Test the new chunking logic on a sample of discourse files.
Shows chunk stats, section distribution, and sample chunk text.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
import django; django.setup()

import re
from pathlib import Path
from scripts.ingest import (
    clean_text, parse_filename, group_into_sections,
    sections_to_chunks, DISCOURSES_DIR,
    T_VERSE, T_ADDRESS, T_HEADER, T_PARABLE, T_TEACHING, T_CLOSING,
)

def test_file(filepath: Path):
    print(f'\n{"=" * 70}')
    print(f'FILE: {filepath.name}')
    print('=' * 70)

    text = filepath.read_text(encoding='utf-8')
    text = clean_text(text)
    metadata = parse_filename(filepath)

    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
    sections = group_into_sections(paragraphs)
    chunks = sections_to_chunks(sections, metadata)

    # Stats
    type_counts = {}
    for s in sections:
        type_counts[s.type] = type_counts.get(s.type, 0) + 1

    wcs = [c['metadata']['word_count'] for c in chunks]
    ctypes = [c['metadata']['section_type'] for c in chunks]
    ctype_counts = {}
    for t in ctypes:
        ctype_counts[t] = ctype_counts.get(t, 0) + 1

    print(f'Paragraphs : {len(paragraphs)}')
    print(f'Sections   : {len(sections)}  {dict(type_counts)}')
    print(f'Chunks     : {len(chunks)}')
    print(f'Word range : {min(wcs)}–{max(wcs)}  avg {int(sum(wcs)/len(wcs))}')
    print(f'Chunk types: {dict(ctype_counts)}')

    print(f'\n--- Sample chunks ---')
    # Show first 3 chunks
    for i, chunk in enumerate(chunks[:3]):
        m = chunk['metadata']
        print(f'\n[Chunk {i}] type={m["section_type"]} | {m["word_count"]}w | '
              f'verse={m["has_verse"]} parable={m["has_parable"]}')
        print(f'TEXT: {chunk["text"][:300]}')
        print(f'EMBED PREFIX: {chunk["embed_text"][:120]}...')

    # Show a parable chunk if any
    parables = [c for c in chunks if c['metadata']['section_type'] == T_PARABLE]
    if parables:
        p = parables[0]
        print(f'\n[Parable chunk] {p["metadata"]["word_count"]}w')
        print(p['text'][:400])

    # Check for any very short or very long chunks
    short = [c for c in chunks if c['metadata']['word_count'] < 80]
    long  = [c for c in chunks if c['metadata']['word_count'] > 500]
    if short:
        print(f'\n⚠  {len(short)} SHORT chunks (<80w): {[c["metadata"]["word_count"] for c in short]}')
    if long:
        print(f'\n⚠  {len(long)} LONG chunks (>500w): {[c["metadata"]["word_count"] for c in long]}')


# Pick 3 files from different years
all_files = sorted(DISCOURSES_DIR.rglob('*.md'))
all_files = [f for f in all_files if f.name != '.gitkeep' and f.stat().st_size > 500]

# Pick one from 2002, one from 2006, one from 2010 (or first/middle/last)
sample = []
years_seen = set()
for f in all_files:
    year = f.parent.name
    if year not in years_seen:
        sample.append(f)
        years_seen.add(year)
    if len(sample) >= 4:
        break

for f in sample:
    test_file(f)

print(f'\n\n{"=" * 70}')
print(f'FULL CORPUS STATS (no embedding/upload)')
print('=' * 70)

all_chunks = 0
all_wcs = []
type_totals = {}
import re as _re

for filepath in all_files:
    text = filepath.read_text(encoding='utf-8')
    text = clean_text(text)
    if not text.strip():
        continue
    metadata = parse_filename(filepath)
    paragraphs = [p.strip() for p in _re.split(r'\n{2,}', text) if p.strip()]
    sections = group_into_sections(paragraphs)
    chunks = sections_to_chunks(sections, metadata)
    all_chunks += len(chunks)
    for c in chunks:
        all_wcs.append(c['metadata']['word_count'])
        t = c['metadata']['section_type']
        type_totals[t] = type_totals.get(t, 0) + 1

print(f'Total files  : {len(all_files)}')
print(f'Total chunks : {all_chunks}')
print(f'Avg per file : {all_chunks // len(all_files) if all_files else 0}')
print(f'Word range   : {min(all_wcs)}–{max(all_wcs)}  avg {int(sum(all_wcs)/len(all_wcs))}')
print(f'Type breakdown: {dict(sorted(type_totals.items()))}')

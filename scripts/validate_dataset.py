"""
Dataset quality validation — run before ingestion.

Checks every .md file in discourses/ against the criteria from the plan:
  - Every chunk >= 50 words (simulated via paragraph-level check)
  - No chunk would exceed 800 words
  - Filename can be parsed for metadata (title, date)
  - Sanskrit/Telugu characters preserved (not corrupted)
  - Deduplication: flag files with very similar opening lines
  - Non-citeable list consistency

Usage:
    python scripts/validate_dataset.py            # validate all .md files
    python scripts/validate_dataset.py --fix      # auto-fix minor whitespace issues
    python scripts/validate_dataset.py --summary  # one-line-per-file summary only
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

import django
django.setup()

# Re-use parsing logic from ingest.py
from scripts.ingest import (  # noqa: E402
    DISCOURSES_DIR,
    NON_CITEABLE_FILE,
    TARGET_CHUNK_MAX,
    chunk_discourse,
    clean_text,
    parse_filename,
    word_count,
)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

MIN_CHUNK_WORDS = 50
MAX_CHUNK_WORDS = 800
MIN_FILE_WORDS = 100        # discard near-empty files
DUPLICATE_HEAD_CHARS = 200  # first N chars used for duplicate detection

# Unicode ranges that should survive conversion intact
INDIC_RE = re.compile(r'[\u0900-\u097F\u0C00-\u0C7F\u0B80-\u0BFF]')

# Corruption markers — bytes that indicate broken encoding
CORRUPT_RE = re.compile(r'[â€™œ\x9d\x80-\x9f]|Ã[^\s]')


# ---------------------------------------------------------------------------
# Per-file checks
# ---------------------------------------------------------------------------

def validate_file(filepath: Path, non_citeable: set, fix: bool = False) -> list[str]:
    """Return a list of issue strings for this file (empty = clean)."""
    issues = []

    raw = filepath.read_text(encoding='utf-8', errors='replace')

    # --- Encoding corruption ---
    corrupt_hits = CORRUPT_RE.findall(raw)
    if corrupt_hits:
        issues.append(f'encoding-corruption: {len(corrupt_hits)} suspect chars ({corrupt_hits[:3]})')

    cleaned = clean_text(raw)

    if not cleaned.strip():
        issues.append('empty-after-cleaning')
        return issues

    total_words = word_count(cleaned)
    if total_words < MIN_FILE_WORDS:
        issues.append(f'too-short: only {total_words} words after cleaning')
        return issues

    # --- Metadata parse ---
    meta = parse_filename(filepath)
    if not meta['date']:
        issues.append('no-date-in-filename')
    if not meta['title']:
        issues.append('no-title-in-filename')

    # --- Non-citeable consistency ---
    if filepath.name in non_citeable and meta['citeable']:
        issues.append('non-citeable-flag-mismatch')

    # --- Chunk-level checks ---
    chunks = chunk_discourse(cleaned, meta)
    if not chunks:
        issues.append('no-chunks-produced')
        return issues

    tiny = [c for c in chunks if c['metadata']['word_count'] < MIN_CHUNK_WORDS]
    huge = [c for c in chunks if c['metadata']['word_count'] > MAX_CHUNK_WORDS]

    if tiny:
        issues.append(f'tiny-chunks({len(tiny)}): indices {[c["metadata"]["chunk_index"] for c in tiny]}')
    if huge:
        issues.append(f'huge-chunks({len(huge)}): indices {[c["metadata"]["chunk_index"] for c in huge]}')

    # --- Fix mode: rewrite with clean text ---
    if fix and (CORRUPT_RE.search(raw) or raw != cleaned + '\n'):
        filepath.write_text(cleaned + '\n', encoding='utf-8')
        issues = [i + ' [auto-fixed]' if 'encoding-corruption' in i else i for i in issues]

    return issues


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def find_duplicates(files: list[Path]) -> list[tuple[Path, Path]]:
    """Return pairs of files whose first DUPLICATE_HEAD_CHARS are identical."""
    heads: dict[str, Path] = {}
    dupes = []
    for f in files:
        head = f.read_text(encoding='utf-8', errors='replace')[:DUPLICATE_HEAD_CHARS].strip()
        if head in heads:
            dupes.append((heads[head], f))
        else:
            heads[head] = f
    return dupes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Validate discourse .md files before ingestion')
    parser.add_argument('--fix', action='store_true', help='Auto-fix encoding/whitespace issues')
    parser.add_argument('--summary', action='store_true', help='One-line-per-file output only')
    args = parser.parse_args()

    non_citeable: set = set()
    if NON_CITEABLE_FILE.exists():
        non_citeable = set(json.loads(NON_CITEABLE_FILE.read_text()))

    files = sorted(DISCOURSES_DIR.rglob('*.md'))
    files = [f for f in files if f.name != '.gitkeep' and f.stat().st_size > 0]

    if not files:
        print('No .md files found in discourses/. Run convert_docs.py first.')
        sys.exit(0)

    print(f'Validating {len(files)} discourse files...\n')

    issues_by_file: dict[Path, list[str]] = {}
    year_counts: dict[str, int] = defaultdict(int)

    for filepath in files:
        year = filepath.parent.name
        year_counts[year] += 1
        issues = validate_file(filepath, non_citeable, fix=args.fix)
        issues_by_file[filepath] = issues

        rel = filepath.relative_to(DISCOURSES_DIR)
        if args.summary:
            status = 'OK' if not issues else f'ISSUES({len(issues)})'
            print(f'  {status:20s}  {rel}')
        elif issues:
            print(f'  {rel}')
            for issue in issues:
                print(f'    - {issue}')

    # --- Duplicate check ---
    dupes = find_duplicates(files)
    if dupes:
        print(f'\nDuplicate files detected ({len(dupes)} pairs):')
        for a, b in dupes:
            print(f'  {a.relative_to(DISCOURSES_DIR)}')
            print(f'  {b.relative_to(DISCOURSES_DIR)}')

    # --- Summary ---
    clean = sum(1 for v in issues_by_file.values() if not v)
    dirty = len(files) - clean

    print(f'\n{"="*60}')
    print(f'Files: {len(files)}  |  Clean: {clean}  |  With issues: {dirty}')
    print(f'Duplicates: {len(dupes)}')
    print('\nFiles per year:')
    for year, count in sorted(year_counts.items()):
        print(f'  {year}: {count}')

    if dirty or dupes:
        print('\nReview issues above before running ingest.py.')
        sys.exit(1)
    else:
        print('\nAll files passed validation. Ready to ingest.')


if __name__ == '__main__':
    main()

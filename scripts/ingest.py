"""
Discourse ingestion pipeline.

Usage:
    python scripts/ingest.py --all              # ingest all .md files in discourses/
    python scripts/ingest.py --file path.md     # ingest a single file
    python scripts/ingest.py --all --dry-run    # parse + chunk only, no embedding/upload
    python scripts/ingest.py --setup-collection # create Qdrant collection (run once)
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import django

# Bootstrap Django so we can read settings (API keys etc.)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
django.setup()

from django.conf import settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DISCOURSES_DIR = Path(__file__).resolve().parent.parent / 'discourses'
NON_CITEABLE_FILE = Path(__file__).resolve().parent.parent / 'config' / 'non_citeable_discourses.json'

EMBEDDING_MODEL = 'text-embedding-3-small'
EMBEDDING_DIM = 1536
COLLECTION_NAME = settings.QDRANT_COLLECTION_NAME

TARGET_CHUNK_MIN = 150   # words
TARGET_CHUNK_MAX = 500   # words
CHUNK_OVERLAP = 50       # words

# Month abbreviations for date parsing
MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'june': 6, 'july': 7, 'august': 8, 'september': 9,
    'october': 10, 'november': 11, 'december': 12,
}

# DD Mon YYYY  or  DD MonYYYY (missing space)  — e.g. "22 July2002", "1 May2008"
DATE_PATTERN = re.compile(
    r'(\d{1,2})\s*(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|'
    r'Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|'
    r'Nov(?:ember)?|Dec(?:ember)?)\s*(\d{4})',
    re.IGNORECASE,
)

# Month DD, YYYY  — American format e.g. "August 31, 2002", "February 24, 2002"
DATE_PATTERN_US = re.compile(
    r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|'
    r'Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|'
    r'Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2}),?\s+(\d{4})',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# 1. Filename parser
# ---------------------------------------------------------------------------

def parse_filename(filepath: Path) -> dict:
    """Extract title, date, event, place from discourse filename."""
    stem = filepath.stem.lstrip('_').strip()

    # Try DD Mon YYYY (primary) then Month DD, YYYY (American fallback)
    match = DATE_PATTERN.search(stem)
    us_match = None
    if not match:
        us_match = DATE_PATTERN_US.search(stem)

    if not match and not us_match:
        return {
            'title': stem,
            'date': None,
            'year': None,
            'event': '',
            'place': '',
            'citeable': True,
        }

    if match:
        day = int(match.group(1))
        month_str = match.group(2).lower()
        month = MONTH_MAP.get(month_str, MONTH_MAP.get(month_str[:3]))
        year = int(match.group(3))
        match_span = match
    else:
        # American format: Month DD, YYYY
        month_str = us_match.group(1).lower()
        month = MONTH_MAP.get(month_str, MONTH_MAP.get(month_str[:3]))
        day = int(us_match.group(2))
        year = int(us_match.group(3))
        match_span = us_match

    try:
        date_obj = datetime(year, month, day).date()
    except ValueError:
        date_obj = None

    before = stem[:match_span.start()].strip(' -').strip()
    after = stem[match_span.end():].strip(' -').strip()

    # Strip "by Bhagavan/Bhagawan Sri Sathya Sai Baba" from title
    title = re.sub(
        r'\s+by\s+Bhagav[ao]n\s+Sri\s+Sathya\s+Sai\s+Baba\s*',
        '', before, flags=re.IGNORECASE
    ).strip()
    title = title.strip('"\'').strip()

    # After the date: "Event - Place" (last segment is place)
    parts = [p.strip() for p in after.split(' - ') if p.strip()]
    if len(parts) >= 2:
        place = parts[-1]
        event = ' - '.join(parts[:-1])
    elif len(parts) == 1:
        event = parts[0]
        place = ''
    else:
        event = ''
        place = ''

    return {
        'title': title,
        'date': str(date_obj) if date_obj else None,
        'year': year,
        'event': event,
        'place': place,
        'citeable': True,  # overridden later from non_citeable_discourses.json
    }


# ---------------------------------------------------------------------------
# 2. Text cleaner
# ---------------------------------------------------------------------------

# Common OCR artifacts in Sai Baba discourse scans
OCR_FIXES = [
    (r'\bSwam[i1](?![\w])', 'Swami'),
    (r'\bBhagaw[a4]n\b', 'Bhagawan'),
    (r'\blov[e3]\b', 'love'),
    (r'â€™', "'"),
    (r'â€œ', '"'),
    (r'â€\x9d', '"'),
    (r'Ã©', 'é'),
    (r'\\--', '—'),
    (r'\\!', '!'),
]

# Lines to strip entirely
STRIP_LINE_PATTERNS = [
    re.compile(r'^\s*Page\s+\d+', re.IGNORECASE),
    re.compile(r'^\s*Sri Sathya Sai Speaks', re.IGNORECASE),
    re.compile(r'^\s*Source:\s*sssbpt', re.IGNORECASE),
    re.compile(r'^\s*Copyright', re.IGNORECASE),
    re.compile(r'^\s*\d+\s*$'),  # bare page numbers
]


def clean_text(text: str) -> str:
    """Remove OCR artifacts, page headers, encoding issues."""
    # Fix OCR artifacts
    for pattern, replacement in OCR_FIXES:
        text = re.sub(pattern, replacement, text)

    # Strip markdown link artifacts from pandoc conversion
    text = re.sub(r'\[([^\]]+)\]\([^\)]*\)', r'\1', text)

    # Remove lines matching strip patterns
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        if any(p.match(line) for p in STRIP_LINE_PATTERNS):
            continue
        cleaned.append(line)
    text = '\n'.join(cleaned)

    # Normalize whitespace: collapse 3+ blank lines to 2
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Strip leading/trailing whitespace per line
    text = '\n'.join(line.rstrip() for line in text.splitlines())

    return text.strip()


# ---------------------------------------------------------------------------
# 3. Section classifier
# ---------------------------------------------------------------------------

VERSE_MARKERS = re.compile(
    r'^#{1,3}\s|'             # markdown headings (often verses)
    r'^\*[^*]|'              # italics lines (transliterated shlokas)
    r'[\u0900-\u097F]|'      # Devanagari characters
    r'[\u0C00-\u0C7F]|'      # Telugu characters
    r'[\u0B80-\u0BFF]',      # Tamil characters
    re.MULTILINE
)

PARABLE_MARKERS = re.compile(
    r'\b(once upon a time|there was a|a small story|once there was|'
    r'let me tell you a story|a student asked|one devotee|'
    r'once a king|there lived)\b',
    re.IGNORECASE
)

CLOSING_MARKERS = re.compile(
    r'\b(i bless you|with my blessings|jai sai ram|prasanthi nilayam|'
    r'bhagawan concluded|thus ended)\b',
    re.IGNORECASE
)


def classify_section(paragraph: str) -> str:
    if CLOSING_MARKERS.search(paragraph):
        return 'closing'
    if VERSE_MARKERS.search(paragraph):
        return 'verse'
    if PARABLE_MARKERS.search(paragraph):
        return 'parable'
    return 'teaching'


# ---------------------------------------------------------------------------
# 4. Smart chunker
# ---------------------------------------------------------------------------

def word_count(text: str) -> int:
    return len(text.split())


def chunk_discourse(text: str, metadata: dict) -> list[dict]:
    """
    Split discourse into chunks of 150–500 words with 50-word overlap.
    Splits at paragraph boundaries; merges short paragraphs; splits long ones.
    """
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]

    # Merge very short paragraphs with the next
    merged = []
    buffer = ''
    for para in paragraphs:
        if buffer:
            candidate = buffer + '\n\n' + para
            if word_count(candidate) < TARGET_CHUNK_MIN:
                buffer = candidate
                continue
            else:
                merged.append(buffer)
                buffer = para
        else:
            buffer = para
    if buffer:
        merged.append(buffer)

    chunks = []
    chunk_index = 0
    overlap_words = []

    for para in merged:
        words = para.split()

        # If paragraph itself is too long, split at sentence boundaries
        if word_count(para) > TARGET_CHUNK_MAX:
            sentences = re.split(r'(?<=[.!?])\s+', para)
            current_words = list(overlap_words)

            for sentence in sentences:
                sentence_words = sentence.split()
                if len(current_words) + len(sentence_words) > TARGET_CHUNK_MAX and len(current_words) >= TARGET_CHUNK_MIN:
                    chunk_text = ' '.join(current_words)
                    chunks.append(_make_chunk(chunk_text, metadata, chunk_index))
                    chunk_index += 1
                    overlap_words = current_words[-CHUNK_OVERLAP:]
                    current_words = list(overlap_words) + sentence_words
                else:
                    current_words.extend(sentence_words)

            if current_words:
                overlap_words = current_words
        else:
            overlap_words = overlap_words + words

        # Emit chunk when we've accumulated enough
        if len(overlap_words) >= TARGET_CHUNK_MAX:
            chunk_text = ' '.join(overlap_words[:TARGET_CHUNK_MAX])
            chunks.append(_make_chunk(chunk_text, metadata, chunk_index))
            chunk_index += 1
            overlap_words = overlap_words[TARGET_CHUNK_MAX - CHUNK_OVERLAP:]

    # Emit remaining words
    if len(overlap_words) >= TARGET_CHUNK_MIN:
        chunk_text = ' '.join(overlap_words)
        chunks.append(_make_chunk(chunk_text, metadata, chunk_index))
        chunk_index += 1
    elif chunks and overlap_words:
        # Append leftover to last chunk rather than creating a tiny chunk
        chunks[-1]['text'] += ' ' + ' '.join(overlap_words)

    # Update total_chunks now that we know the final count
    total = len(chunks)
    for c in chunks:
        c['metadata']['total_chunks'] = total

    return chunks


def _make_chunk(text: str, metadata: dict, index: int) -> dict:
    return {
        'text': text.strip(),
        'metadata': {
            **metadata,
            'chunk_index': index,
            'total_chunks': 0,       # filled in after all chunks are created
            'section_type': classify_section(text),
            'word_count': word_count(text),
        },
    }


# ---------------------------------------------------------------------------
# 5. Embedder
# ---------------------------------------------------------------------------

def embed_chunks(chunks: list[dict], batch_size: int = 100) -> list[dict]:
    """Embed chunk texts using OpenAI text-embedding-3-small."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    texts = [c['text'] for c in chunks]
    embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        print(f'  Embedding batch {i // batch_size + 1} ({len(batch)} chunks)...')
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        embeddings.extend([e.embedding for e in response.data])
        time.sleep(0.1)  # gentle rate limiting

    for chunk, embedding in zip(chunks, embeddings):
        chunk['embedding'] = embedding

    return chunks


# ---------------------------------------------------------------------------
# 6. Qdrant uploader
# ---------------------------------------------------------------------------

QDRANT_TIMEOUT = 120        # seconds — generous for cross-continent latency
QDRANT_UPLOAD_BATCH = 20   # points per upsert call — keeps payload small
QDRANT_RETRY_LIMIT = 3


def _qdrant_client():
    from qdrant_client import QdrantClient
    return QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=QDRANT_TIMEOUT,
    )


def setup_collection():
    """Create the Qdrant collection. Run once before first ingestion."""
    from qdrant_client.models import Distance, VectorParams

    client = _qdrant_client()
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in existing:
        print(f'Collection "{COLLECTION_NAME}" already exists.')
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )
    print(f'Created collection "{COLLECTION_NAME}" (dim={EMBEDDING_DIM}, cosine).')


def already_ingested(source_file: str) -> bool:
    """Return True if any point for this source_file already exists in Qdrant."""
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    try:
        client = _qdrant_client()
        result = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(must=[
                FieldCondition(key='source_file', match=MatchValue(value=source_file))
            ]),
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        return len(result[0]) > 0
    except Exception:
        return False


def upload_to_qdrant(chunks: list[dict], source_file: str):
    """Upload embedded chunks to Qdrant in small batches with retry."""
    import hashlib
    from qdrant_client.models import PointStruct

    client = _qdrant_client()

    points = []
    for chunk in chunks:
        point_id = int(hashlib.md5(
            f'{source_file}::{chunk["metadata"]["chunk_index"]}'.encode()
        ).hexdigest(), 16) % (2 ** 63)

        points.append(PointStruct(
            id=point_id,
            vector=chunk['embedding'],
            payload={
                'text': chunk['text'],
                **chunk['metadata'],
                'source_file': source_file,
            },
        ))

    uploaded = 0
    for i in range(0, len(points), QDRANT_UPLOAD_BATCH):
        batch = points[i:i + QDRANT_UPLOAD_BATCH]
        for attempt in range(1, QDRANT_RETRY_LIMIT + 1):
            try:
                client.upsert(collection_name=COLLECTION_NAME, points=batch)
                uploaded += len(batch)
                break
            except Exception as exc:
                if attempt == QDRANT_RETRY_LIMIT:
                    print(f'  ERROR uploading batch {i // QDRANT_UPLOAD_BATCH + 1} after {QDRANT_RETRY_LIMIT} attempts: {exc}')
                    raise
                print(f'  Retry {attempt}/{QDRANT_RETRY_LIMIT} for batch {i // QDRANT_UPLOAD_BATCH + 1}...')
                time.sleep(3 * attempt)

    print(f'  Uploaded {uploaded} chunks to Qdrant.')


# ---------------------------------------------------------------------------
# 7. Non-citeable handling
# ---------------------------------------------------------------------------

def load_non_citeable() -> set:
    if NON_CITEABLE_FILE.exists():
        return set(json.loads(NON_CITEABLE_FILE.read_text()))
    return set()


# ---------------------------------------------------------------------------
# 8. Main pipeline
# ---------------------------------------------------------------------------

def process_file(filepath: Path, non_citeable: set, dry_run: bool = False,
                 resume: bool = False) -> int:
    """Process one discourse file. Returns number of chunks created."""
    source_file = str(filepath.relative_to(DISCOURSES_DIR))

    if resume and not dry_run and already_ingested(source_file):
        print(f'  [skip] {filepath.name} (already in Qdrant)')
        return 0

    print(f'\nProcessing: {filepath.name}')

    text = filepath.read_text(encoding='utf-8')
    text = clean_text(text)

    if not text.strip():
        print('  Skipped: empty after cleaning.')
        return 0

    metadata = parse_filename(filepath)
    if filepath.name in non_citeable:
        metadata['citeable'] = False

    print(f'  Title  : {metadata["title"]}')
    print(f'  Date   : {metadata["date"]}  |  Event: {metadata["event"]}  |  Place: {metadata["place"]}')

    chunks = chunk_discourse(text, metadata)
    print(f'  Chunks : {len(chunks)}  (words: {[c["metadata"]["word_count"] for c in chunks]})')

    if dry_run:
        print('  [dry-run] Skipping embedding and upload.')
        return len(chunks)

    if not settings.OPENAI_API_KEY:
        print('  ERROR: OPENAI_API_KEY not set in .env')
        return 0

    chunks = embed_chunks(chunks)

    if not settings.QDRANT_URL or not settings.QDRANT_API_KEY:
        print('  ERROR: QDRANT_URL or QDRANT_API_KEY not set in .env')
        return 0

    upload_to_qdrant(chunks, source_file=source_file)

    return len(chunks)


def main():
    parser = argparse.ArgumentParser(description='Sai Uvacha discourse ingestion pipeline')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true', help='Process all .md files in discourses/')
    group.add_argument('--file', type=str, help='Process a single .md file')
    group.add_argument('--setup-collection', action='store_true', help='Create Qdrant collection')
    parser.add_argument('--dry-run', action='store_true', help='Parse and chunk only, no API calls')
    parser.add_argument('--resume', action='store_true', help='Skip files already uploaded to Qdrant')
    args = parser.parse_args()

    if args.setup_collection:
        setup_collection()
        return

    non_citeable = load_non_citeable()

    if args.file:
        filepath = Path(args.file)
        if not filepath.is_absolute():
            filepath = Path(__file__).parent.parent / filepath
        if not filepath.exists():
            print(f'File not found: {filepath}')
            sys.exit(1)
        count = process_file(filepath, non_citeable, dry_run=args.dry_run, resume=args.resume)
        print(f'\nDone. {count} chunks.')

    elif args.all:
        files = sorted(DISCOURSES_DIR.rglob('*.md'))
        # Skip .gitkeep
        files = [f for f in files if f.name != '.gitkeep' and f.stat().st_size > 0]

        print(f'Found {len(files)} discourse files.')
        total_chunks = 0
        for filepath in files:
            total_chunks += process_file(filepath, non_citeable, dry_run=args.dry_run, resume=args.resume)

        print(f'\n{"="*60}')
        print(f'Ingestion complete. {len(files)} files, {total_chunks} total chunks.')


if __name__ == '__main__':
    main()

"""
Discourse ingestion pipeline — structure-aware semantic chunking.

Chunking strategy:
  1. Clean text (OCR, encoding, page noise)
  2. Parse paragraphs into typed structural elements:
       VERSE     — blockquote lines (> ...) or Devanagari/Telugu script
       ADDRESS   — audience address ("Embodiments of Love!", "Dear Students")
       HEADER    — bold section heading (**text**)
       PARABLE   — paragraph opening a story ("Once upon a time...", "There was a king...")
       TEACHING  — regular discourse paragraph
       CLOSING   — blessing/closing paragraph
  3. Group typed elements into semantic sections:
       - Verse + next 2 paragraphs (translation + explanation) → one section
       - Address/Header → marks start of new teaching section
       - Parable paragraphs → kept together until story resolves
       - Teaching paragraphs → accumulated into sections of 150–400 words
       - Closing → its own section
  4. Convert sections to chunks with sentence-level overlap (last 2 sentences
     of previous chunk prepended to next)
  5. Contextual retrieval prefix: prepend discourse source to embedded text
     so every chunk knows where it came from even without metadata lookup

Usage:
    python scripts/ingest.py --all              # ingest all .md files
    python scripts/ingest.py --file path.md     # ingest single file
    python scripts/ingest.py --all --resume     # skip already-uploaded files
    python scripts/ingest.py --all --clear      # wipe collection and re-ingest
    python scripts/ingest.py --all --dry-run    # parse + chunk only, no API calls
    python scripts/ingest.py --setup-collection # create Qdrant collection (once)
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import django

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
EMBEDDING_DIM   = 1536
COLLECTION_NAME = settings.QDRANT_COLLECTION_NAME

# Chunk size targets (words)
CHUNK_MIN         = 100   # below this, merge with adjacent
CHUNK_TARGET      = 250   # ideal size
CHUNK_MAX         = 400   # hard max for regular chunks
CHUNK_MAX_PARABLE = 500   # parables — still bounded, split at sentence boundary if needed
CHUNK_HARD_CAP    = 500   # absolute maximum — no chunk may exceed this
OVERSIZED_PARA    = 300   # paragraphs longer than this are pre-split before grouping
OVERLAP_SENTENCES = 2     # sentences from tail of previous chunk prepended to next

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'june': 6, 'july': 7, 'august': 8, 'september': 9,
    'october': 10, 'november': 11, 'december': 12,
}

DATE_PATTERN = re.compile(
    r'(\d{1,2})\s*(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|'
    r'Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|'
    r'Nov(?:ember)?|Dec(?:ember)?)\s*(\d{4})',
    re.IGNORECASE,
)
DATE_PATTERN_US = re.compile(
    r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|'
    r'Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|'
    r'Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2}),?\s+(\d{4})',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Structural element types
# ---------------------------------------------------------------------------

T_VERSE    = 'verse'
T_ADDRESS  = 'address'
T_HEADER   = 'header'
T_PARABLE  = 'parable'
T_TEACHING = 'teaching'
T_CLOSING  = 'closing'

# ---------------------------------------------------------------------------
# 1. Filename parser
# ---------------------------------------------------------------------------

def parse_filename(filepath: Path) -> dict:
    stem = filepath.stem.lstrip('_').strip()

    match = DATE_PATTERN.search(stem)
    us_match = None
    if not match:
        us_match = DATE_PATTERN_US.search(stem)

    if not match and not us_match:
        return {'title': stem, 'date': None, 'year': None,
                'event': '', 'place': '', 'citeable': True}

    if match:
        day, month_str, year = int(match.group(1)), match.group(2).lower(), int(match.group(3))
        month = MONTH_MAP.get(month_str, MONTH_MAP.get(month_str[:3]))
        span = match
    else:
        month_str, day, year = us_match.group(1).lower(), int(us_match.group(2)), int(us_match.group(3))
        month = MONTH_MAP.get(month_str, MONTH_MAP.get(month_str[:3]))
        span = us_match

    try:
        date_obj = datetime(year, month, day).date()
    except ValueError:
        date_obj = None

    before = stem[:span.start()].strip(' -').strip()
    after  = stem[span.end():].strip(' -').strip()

    title = re.sub(
        r'\s+by\s+Bhagav[ao]n\s+Sri\s+Sathya\s+Sai\s+Baba\s*',
        '', before, flags=re.IGNORECASE,
    ).strip().strip('"\'').strip()

    parts = [p.strip() for p in after.split(' - ') if p.strip()]
    if len(parts) >= 2:
        place = parts[-1]
        event = ' - '.join(parts[:-1])
    elif len(parts) == 1:
        event, place = parts[0], ''
    else:
        event, place = '', ''

    return {
        'title':    title,
        'date':     str(date_obj) if date_obj else None,
        'year':     year,
        'event':    event,
        'place':    place,
        'citeable': True,
    }


# ---------------------------------------------------------------------------
# 2. Text cleaner
# ---------------------------------------------------------------------------

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
    # Pandoc artefacts: backslash line-continuation in blockquotes → space
    (r'\\\n', ' '),
    # Collapsed smart quotes
    (r'\u2018|\u2019', "'"),
    (r'\u201c|\u201d', '"'),
]

STRIP_LINE_RE = [
    re.compile(r'^\s*Page\s+\d+', re.IGNORECASE),
    re.compile(r'^\s*Sri Sathya Sai Speaks', re.IGNORECASE),
    re.compile(r'^\s*Source:\s*sssbpt', re.IGNORECASE),
    re.compile(r'^\s*Copyright', re.IGNORECASE),
    re.compile(r'^\s*\d+\s*$'),
    re.compile(r'^\s*#{1,6}\s*$'),   # bare markdown heading with no text
]


def clean_text(text: str) -> str:
    for pattern, replacement in OCR_FIXES:
        text = re.sub(pattern, replacement, text)

    # Remove markdown links (pandoc artefacts)
    text = re.sub(r'\[([^\]]+)\]\([^\)]*\)', r'\1', text)

    lines = []
    for line in text.splitlines():
        if any(p.match(line) for p in STRIP_LINE_RE):
            continue
        lines.append(line.rstrip())

    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ---------------------------------------------------------------------------
# 3. Sentence tokenizer
# ---------------------------------------------------------------------------

_ABBREV_PROTECT = [
    'Dr.', 'Mr.', 'Mrs.', 'Ms.', 'Prof.', 'vs.', 'etc.',
    'e.g.', 'i.e.', 'No.', 'Vol.',
    'Jan.', 'Feb.', 'Mar.', 'Apr.', 'Jun.', 'Jul.',
    'Aug.', 'Sep.', 'Sept.', 'Oct.', 'Nov.', 'Dec.',
    'St.', 'Mt.',
]
_ABBREV_MAP = {a: a.replace('.', '\x00') for a in _ABBREV_PROTECT}
_ABBREV_UNMAP = {v: k for k, v in _ABBREV_MAP.items()}

_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z\"\(\'])')


def split_sentences(text: str) -> list[str]:
    """Split text into complete sentences, respecting common abbreviations."""
    protected = text
    for orig, safe in _ABBREV_MAP.items():
        protected = protected.replace(orig, safe)

    parts = _SENT_SPLIT.split(protected)

    sentences = []
    for part in parts:
        for safe, orig in _ABBREV_UNMAP.items():
            part = part.replace(safe, orig)
        part = part.strip()
        if part:
            sentences.append(part)

    return sentences


def tail_sentences(text: str, n: int) -> str:
    """Return the last n complete sentences from text."""
    sents = split_sentences(text)
    return ' '.join(sents[-n:]) if len(sents) >= n else text


# ---------------------------------------------------------------------------
# 4. Pre-split oversized paragraphs
# ---------------------------------------------------------------------------

def pre_split_paragraphs(paragraphs: list[str]) -> list[str]:
    """
    Some discourse files lost double-newlines during pandoc conversion and
    arrive as one or a few giant paragraphs. Break any paragraph that exceeds
    OVERSIZED_PARA words into smaller sentence-aligned pieces so the structural
    classifier and grouper can work properly.
    Blockquote lines (starting with >) are never split.
    """
    result = []
    for para in paragraphs:
        if para.startswith('>'):
            result.append(para)
            continue
        if _wc(para) <= OVERSIZED_PARA:
            result.append(para)
            continue
        # Split at sentence boundaries
        pieces = _split_section_by_sentences(para, OVERSIZED_PARA)
        result.extend(p for p in pieces if p.strip())
    return result


# ---------------------------------------------------------------------------
# 5. Paragraph-level structural classifier
# ---------------------------------------------------------------------------

_ADDRESS_RE = re.compile(
    r'^\*{1,2}(Embodiments\s+of\s+(Pure\s+)?Love|'
    r'Prema\s+Swaro+pulara|Divya\s+Atma\s+Swaro+pa|'
    r'Dear\s+(Students?|Devotees?|Children|Boys?|Girls?)|'
    r'Beloved\s+(Devotees?|Children)|'
    r'Dear\s+ones?|Bangaru)\b.*\*{1,2}',
    re.IGNORECASE,
)

_HEADER_RE = re.compile(r'^\*{1,2}[A-Z][^\n]{3,60}\*{1,2}$')

_PARABLE_RE = re.compile(
    r'\b(once\s+upon\s+a\s+time|once\s+there\s+(was|lived)|'
    r'there\s+(was|lived|once)\s+(a|an)\b|'
    r'a\s+(small\s+)?story\s+(is\s+told|goes)|'
    r'let\s+me\s+tell\s+you\s+a\s+story|'
    r'once\s+a\s+(king|student|devotee|brahmin|farmer|man|woman)|'
    r'in\s+the\s+days?\s+of\s+(yore|old)|'
    r'ages?\s+ago|long\s+ago\b)',
    re.IGNORECASE,
)

_CLOSING_RE = re.compile(
    r'\b(i\s+bless\s+you|with\s+my\s+(love\s+and\s+)?blessings?|'
    r'jai\s+sai\s+ram|prasanthi\s+nilayam|'
    r'bhagawan\s+(concluded|ended|sang)|'
    r'thus\s+ended|my\s+blessings?\s+are|'
    r'may\s+(god\s+bless|swami\s+bless)|'
    r'sai\s+ram\s*$)',
    re.IGNORECASE,
)

_VERSE_INLINE = re.compile(
    r'[\u0900-\u097F]|'   # Devanagari
    r'[\u0C00-\u0C7F]|'   # Telugu
    r'[\u0B80-\u0BFF]|'   # Tamil
    r'[\u0C80-\u0CFF]',   # Kannada
)


def classify_paragraph(para: str) -> str:
    stripped = para.strip()

    # Blockquote lines — verse/shloka
    if stripped.startswith('>'):
        return T_VERSE

    # Contains Indian script
    if _VERSE_INLINE.search(stripped):
        return T_VERSE

    # Audience address (bold, specific phrases)
    if _ADDRESS_RE.match(stripped):
        return T_ADDRESS

    # Bold section header (not address)
    if _HEADER_RE.match(stripped) and not _ADDRESS_RE.match(stripped):
        return T_HEADER

    # Closing markers
    if _CLOSING_RE.search(stripped):
        return T_CLOSING

    # Parable opening
    if _PARABLE_RE.search(stripped):
        return T_PARABLE

    return T_TEACHING


# ---------------------------------------------------------------------------
# 5. Group paragraphs into semantic sections
# ---------------------------------------------------------------------------

def _wc(text: str) -> int:
    return len(text.split())


class Section:
    __slots__ = ('type', 'paragraphs')

    def __init__(self, type_: str):
        self.type = type_
        self.paragraphs: list[str] = []

    def text(self) -> str:
        return '\n\n'.join(self.paragraphs)

    def word_count(self) -> int:
        return _wc(self.text())

    def is_empty(self) -> bool:
        return not self.paragraphs


def group_into_sections(paragraphs: list[str]) -> list[Section]:
    """
    Walk through typed paragraphs and group them into semantic sections.

    Rules:
    - VERSE: opens a new verse-section; collect verse + next 2 paras (translation+explanation)
    - ADDRESS / HEADER: flush current section, start new teaching section with this as heading
    - PARABLE: flush current, start parable section; keep accumulating until
               the parable resolves (word count >= 100 and we hit a teaching/closing para
               that doesn't continue the story)
    - CLOSING: flush current, start closing section
    - TEACHING: accumulate into current section; flush when word count reaches CHUNK_TARGET
    """
    sections: list[Section] = []
    current = Section(T_TEACHING)

    def flush():
        nonlocal current
        if not current.is_empty():
            sections.append(current)
        current = Section(T_TEACHING)

    i = 0
    while i < len(paragraphs):
        para = paragraphs[i]
        kind = classify_paragraph(para)

        if kind == T_VERSE:
            # Verse section: verse block + following translation/explanation paragraphs
            flush()
            verse_section = Section(T_VERSE)
            verse_section.paragraphs.append(para)
            i += 1
            # Collect blockquote continuation lines
            while i < len(paragraphs) and paragraphs[i].strip().startswith('>'):
                verse_section.paragraphs.append(paragraphs[i])
                i += 1
            # Pull in up to 2 more paragraphs (translation + first explanation)
            extra = 0
            while i < len(paragraphs) and extra < 2:
                next_kind = classify_paragraph(paragraphs[i])
                if next_kind in (T_VERSE, T_ADDRESS, T_HEADER, T_CLOSING):
                    break
                verse_section.paragraphs.append(paragraphs[i])
                i += 1
                extra += 1
            sections.append(verse_section)
            current = Section(T_TEACHING)
            continue

        elif kind in (T_ADDRESS, T_HEADER):
            # Start of a new topic — flush previous, begin fresh teaching section
            flush()
            current = Section(T_TEACHING)
            # Include the address/header as the opening line of the new section
            current.paragraphs.append(para)
            i += 1
            continue

        elif kind == T_PARABLE:
            # Flush current teaching content, then accumulate the whole parable
            flush()
            parable_section = Section(T_PARABLE)
            parable_section.paragraphs.append(para)
            i += 1
            # Keep adding paragraphs until the parable resolves:
            # - we've accumulated enough words AND hit a non-story paragraph
            # - OR we hit a verse / address / header / closing
            while i < len(paragraphs):
                next_kind = classify_paragraph(paragraphs[i])
                if next_kind in (T_VERSE, T_ADDRESS, T_HEADER, T_CLOSING):
                    break
                parable_section.paragraphs.append(paragraphs[i])
                i += 1
                # A parable is "resolved" when it has >= CHUNK_MIN words and
                # the new paragraph looks like a moral/lesson (very heuristic)
                if parable_section.word_count() >= CHUNK_MIN and next_kind == T_TEACHING:
                    # Check if this para contains common parable-resolution markers
                    last = parable_section.paragraphs[-1]
                    if re.search(
                        r'\b(thus|therefore|so you see|the lesson|moral|'
                        r'in the same way|similarly|just as|so too)\b',
                        last, re.IGNORECASE,
                    ):
                        # Include one more explanation paragraph then stop
                        if i < len(paragraphs) and classify_paragraph(paragraphs[i]) == T_TEACHING:
                            parable_section.paragraphs.append(paragraphs[i])
                            i += 1
                        break
            sections.append(parable_section)
            current = Section(T_TEACHING)
            continue

        elif kind == T_CLOSING:
            flush()
            closing = Section(T_CLOSING)
            closing.paragraphs.append(para)
            i += 1
            while i < len(paragraphs) and classify_paragraph(paragraphs[i]) == T_CLOSING:
                closing.paragraphs.append(paragraphs[i])
                i += 1
            sections.append(closing)
            current = Section(T_TEACHING)
            continue

        else:  # T_TEACHING
            current.paragraphs.append(para)
            i += 1
            # Flush when we've reached the soft target — but only at a paragraph
            # boundary (which we always are here)
            if current.word_count() >= CHUNK_TARGET:
                flush()
            continue

    flush()
    return [s for s in sections if not s.is_empty()]


# ---------------------------------------------------------------------------
# 6. Convert sections → chunks with sentence-level overlap
# ---------------------------------------------------------------------------

def _split_section_by_sentences(text: str, max_words: int) -> list[str]:
    """
    Split a long text into sentence-aligned pieces, each ≤ max_words.
    Falls back to word-window splitting if a single sentence exceeds max_words.
    """
    sentences = split_sentences(text)
    pieces = []
    current_sents: list[str] = []
    current_wc = 0

    for sent in sentences:
        sw = _wc(sent)
        if sw > max_words:
            # Single sentence exceeds max — flush current, then word-window split the sentence
            if current_sents:
                pieces.append(' '.join(current_sents))
                current_sents = []
                current_wc = 0
            words = sent.split()
            for start in range(0, len(words), max_words):
                pieces.append(' '.join(words[start:start + max_words]))
        elif current_wc + sw > max_words and current_sents:
            pieces.append(' '.join(current_sents))
            current_sents = [sent]
            current_wc = sw
        else:
            current_sents.append(sent)
            current_wc += sw

    if current_sents:
        pieces.append(' '.join(current_sents))

    return [p for p in pieces if p.strip()]


def sections_to_chunks(sections: list[Section], metadata: dict) -> list[dict]:
    """
    Convert semantic sections into final chunks with sentence-level overlap.

    Each chunk dict has:
        text          — the chunk text (for display and LLM context)
        embed_text    — text with contextual prefix (used for embedding)
        metadata      — discourse metadata + chunk stats
    """
    # Build contextual prefix for embedding (Contextual Retrieval technique)
    prefix_parts = []
    if metadata.get('title'):
        prefix_parts.append(f'"{metadata["title"]}"')
    if metadata.get('event'):
        prefix_parts.append(f'at {metadata["event"]}')
    if metadata.get('place'):
        prefix_parts.append(f'in {metadata["place"]}')
    if metadata.get('year'):
        prefix_parts.append(f'({metadata["year"]})')
    context_prefix = (
        f'Bhagawan Sri Sathya Sai Baba, {" ".join(prefix_parts)}: '
        if prefix_parts else 'Bhagawan Sri Sathya Sai Baba: '
    )

    raw_chunks: list[dict] = []   # {text, type, has_verse, has_parable}

    for section in sections:
        text = section.text()
        wc   = _wc(text)

        # Verse sections: keep whole, even if a bit large
        if section.type == T_VERSE:
            raw_chunks.append({
                'text': text, 'type': T_VERSE,
                'has_verse': True, 'has_parable': False,
            })

        # Parable sections: keep whole up to CHUNK_MAX_PARABLE
        elif section.type == T_PARABLE:
            if wc <= CHUNK_MAX_PARABLE:
                raw_chunks.append({
                    'text': text, 'type': T_PARABLE,
                    'has_verse': False, 'has_parable': True,
                })
            else:
                # Very long parable — split at sentence boundaries only
                pieces = _split_section_by_sentences(text, CHUNK_MAX_PARABLE)
                for piece in pieces:
                    raw_chunks.append({
                        'text': piece, 'type': T_PARABLE,
                        'has_verse': False, 'has_parable': True,
                    })

        # Closing: split if large (same as teaching)
        elif section.type == T_CLOSING:
            if wc >= 30:
                if wc <= CHUNK_MAX:
                    raw_chunks.append({
                        'text': text, 'type': T_CLOSING,
                        'has_verse': False, 'has_parable': False,
                    })
                else:
                    pieces = _split_section_by_sentences(text, CHUNK_MAX)
                    for piece in pieces:
                        raw_chunks.append({
                            'text': piece, 'type': T_CLOSING,
                            'has_verse': False, 'has_parable': False,
                        })

        # Teaching sections
        else:
            if wc <= CHUNK_MAX:
                raw_chunks.append({
                    'text': text, 'type': T_TEACHING,
                    'has_verse': False, 'has_parable': False,
                })
            else:
                pieces = _split_section_by_sentences(text, CHUNK_MAX)
                for piece in pieces:
                    raw_chunks.append({
                        'text': piece, 'type': T_TEACHING,
                        'has_verse': False, 'has_parable': False,
                    })

    # Merge tiny chunks — two passes:
    # Pass 1 (backward): merge tiny chunk into its predecessor
    # Pass 2 (forward):  merge any remaining tiny chunks into their successor
    # Verse chunks are never merged — they are self-contained.

    def _do_merge(chunks_in: list[dict], direction: str) -> list[dict]:
        if direction == 'backward':
            seq = chunks_in
        else:
            seq = list(reversed(chunks_in))

        out: list[dict] = []
        for chunk in seq:
            wc = _wc(chunk['text'])
            if out and wc < CHUNK_MIN and chunk['type'] != T_VERSE:
                if direction == 'backward':
                    out[-1]['text'] += '\n\n' + chunk['text']
                else:
                    out[-1]['text'] = chunk['text'] + '\n\n' + out[-1]['text']
                out[-1]['has_verse']   = out[-1]['has_verse']   or chunk['has_verse']
                out[-1]['has_parable'] = out[-1]['has_parable'] or chunk['has_parable']
            else:
                out.append(dict(chunk))

        return out if direction == 'backward' else list(reversed(out))

    merged = _do_merge(_do_merge(raw_chunks, 'backward'), 'forward')

    # Hard safety cap — no chunk may exceed CHUNK_HARD_CAP regardless of type
    capped: list[dict] = []
    for chunk in merged:
        if _wc(chunk['text']) > CHUNK_HARD_CAP:
            pieces = _split_section_by_sentences(chunk['text'], CHUNK_HARD_CAP)
            for piece in pieces:
                capped.append({**chunk, 'text': piece})
        else:
            capped.append(chunk)
    merged = capped

    # Apply sentence-level overlap and build final chunk dicts
    final: list[dict] = []
    for idx, chunk in enumerate(merged):
        text = chunk['text'].strip()

        # Build overlap prefix from the tail of the previous chunk
        overlap_prefix = ''
        if idx > 0 and chunk['type'] == T_TEACHING:
            prev_text = merged[idx - 1]['text']
            tail = tail_sentences(prev_text, OVERLAP_SENTENCES)
            if tail and tail != prev_text:
                overlap_prefix = tail + ' '

        display_text  = (overlap_prefix + text).strip()
        embedded_text = context_prefix + display_text

        final.append({
            'text':       display_text,
            'embed_text': embedded_text,
            'metadata': {
                **metadata,
                'chunk_index':  idx,
                'total_chunks': 0,       # filled below
                'section_type': chunk['type'],
                'has_verse':    chunk['has_verse'],
                'has_parable':  chunk['has_parable'],
                'word_count':   _wc(display_text),
            },
        })

    total = len(final)
    for c in final:
        c['metadata']['total_chunks'] = total

    return final


# ---------------------------------------------------------------------------
# 7. Embedder
# ---------------------------------------------------------------------------

def embed_chunks(chunks: list[dict], batch_size: int = 100) -> list[dict]:
    """Embed each chunk's embed_text field using OpenAI text-embedding-3-small."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    texts = [c['embed_text'] for c in chunks]

    embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        print(f'  Embedding batch {i // batch_size + 1} ({len(batch)} chunks)...')
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        embeddings.extend([e.embedding for e in response.data])
        time.sleep(0.1)

    for chunk, embedding in zip(chunks, embeddings):
        chunk['embedding'] = embedding

    return chunks


# ---------------------------------------------------------------------------
# 8. Qdrant collection + uploader
# ---------------------------------------------------------------------------

QDRANT_TIMEOUT      = 120
QDRANT_UPLOAD_BATCH = 20
QDRANT_RETRY_LIMIT  = 3


def _qdrant_client():
    from qdrant_client import QdrantClient
    return QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=QDRANT_TIMEOUT,
    )


def setup_collection(clear: bool = False):
    from qdrant_client.models import Distance, VectorParams
    client = _qdrant_client()
    existing = [c.name for c in client.get_collections().collections]

    if COLLECTION_NAME in existing:
        if clear:
            client.delete_collection(COLLECTION_NAME)
            print(f'Deleted existing collection "{COLLECTION_NAME}".')
        else:
            print(f'Collection "{COLLECTION_NAME}" already exists.')
            return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )
    print(f'Created collection "{COLLECTION_NAME}" (dim={EMBEDDING_DIM}, cosine).')


def already_ingested(source_file: str) -> bool:
    from qdrant_client.models import FieldCondition, Filter, MatchValue
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
                'text':        chunk['text'],       # display text (no prefix)
                'embed_text':  chunk['embed_text'],  # what was embedded
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
                    raise
                print(f'  Retry {attempt}/{QDRANT_RETRY_LIMIT}...')
                time.sleep(3 * attempt)

    print(f'  Uploaded {uploaded} chunks.')


# ---------------------------------------------------------------------------
# 9. Non-citeable loader
# ---------------------------------------------------------------------------

def load_non_citeable() -> set:
    if NON_CITEABLE_FILE.exists():
        return set(json.loads(NON_CITEABLE_FILE.read_text()))
    return set()


# ---------------------------------------------------------------------------
# 10. Main pipeline
# ---------------------------------------------------------------------------

def process_file(
    filepath: Path,
    non_citeable: set,
    dry_run: bool = False,
    resume: bool = False,
) -> int:
    source_file = str(filepath.relative_to(DISCOURSES_DIR))

    if resume and not dry_run and already_ingested(source_file):
        print(f'  [skip] {filepath.name}')
        return 0

    print(f'\nProcessing: {filepath.name}')

    text = filepath.read_text(encoding='utf-8')
    text = clean_text(text)
    if not text.strip():
        print('  Skipped: empty.')
        return 0

    metadata = parse_filename(filepath)
    if filepath.name in non_citeable:
        metadata['citeable'] = False

    print(f'  Title : {metadata["title"]}')
    print(f'  Date  : {metadata["date"]}  |  Event: {metadata["event"]}  |  Place: {metadata["place"]}')

    # Split into paragraphs (single blank line = paragraph separator)
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]

    # Pre-split any oversized paragraphs (files where pandoc lost blank lines)
    paragraphs = pre_split_paragraphs(paragraphs)

    # Group into semantic sections
    sections = group_into_sections(paragraphs)

    section_summary = {}
    for s in sections:
        section_summary[s.type] = section_summary.get(s.type, 0) + 1

    # Convert to chunks
    chunks = sections_to_chunks(sections, metadata)

    wcs = [c['metadata']['word_count'] for c in chunks]
    types = [c['metadata']['section_type'] for c in chunks]
    print(f'  Sections  : {dict(section_summary)}')
    print(f'  Chunks    : {len(chunks)}  avg {int(sum(wcs)/len(wcs)) if wcs else 0}w  '
          f'range {min(wcs) if wcs else 0}–{max(wcs) if wcs else 0}w')
    print(f'  Chunk types: {sorted(set(types))}')

    if dry_run:
        print('  [dry-run] Skipping embedding and upload.')
        if len(chunks) > 0:
            print(f'  Sample chunk 0:\n    {chunks[0]["text"][:200]}...')
        return len(chunks)

    if not settings.OPENAI_API_KEY:
        print('  ERROR: OPENAI_API_KEY not set')
        return 0

    chunks = embed_chunks(chunks)

    if not settings.QDRANT_URL or not settings.QDRANT_API_KEY:
        print('  ERROR: QDRANT credentials not set')
        return 0

    upload_to_qdrant(chunks, source_file=source_file)
    return len(chunks)


def main():
    parser = argparse.ArgumentParser(description='Sai Uvacha discourse ingestion pipeline')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all',              action='store_true', help='Process all .md files')
    group.add_argument('--file',             type=str,            help='Process a single .md file')
    group.add_argument('--setup-collection', action='store_true', help='Create Qdrant collection')
    parser.add_argument('--dry-run', action='store_true', help='Parse+chunk only, no API calls')
    parser.add_argument('--resume',  action='store_true', help='Skip already-uploaded files')
    parser.add_argument('--clear',   action='store_true', help='Delete and recreate collection before ingesting')
    args = parser.parse_args()

    if args.setup_collection:
        setup_collection(clear=False)
        return

    if args.clear and not args.dry_run:
        setup_collection(clear=True)

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
        files = [f for f in files if f.name != '.gitkeep' and f.stat().st_size > 0]
        print(f'Found {len(files)} discourse files.')

        total_chunks = 0
        for filepath in files:
            total_chunks += process_file(
                filepath, non_citeable, dry_run=args.dry_run, resume=args.resume
            )

        print(f'\n{"=" * 60}')
        print(f'Ingestion complete. {len(files)} files, {total_chunks} total chunks.')


if __name__ == '__main__':
    main()

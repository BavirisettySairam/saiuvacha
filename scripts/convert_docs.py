"""
Batch convert .docx discourse files to .md using pandoc.

Reads from a zip archive (or a directory) and outputs .md files
into discourses/<year>/ preserving the filename convention expected
by ingest.py.

Usage:
    # Extract + convert all .docx from the zip:
    python scripts/convert_docs.py --zip "discourses/2002/Divine Discourses-*.zip"

    # Convert all .docx in a directory (recursive):
    python scripts/convert_docs.py --dir path/to/docx/folder

    # Dry-run: show what would be converted without writing files:
    python scripts/convert_docs.py --zip path/to/file.zip --dry-run
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DISCOURSES_DIR = REPO_ROOT / 'discourses'

# Year pattern — used to route files to discourses/<year>/
YEAR_RE = re.compile(r'\b(19|20)\d{2}\b')

# Strip leading/trailing whitespace and common prefix noise from filenames
LEADING_NOISE_RE = re.compile(r'^[\s_]+')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_year(name: str) -> str | None:
    """Return the first 4-digit year found in the filename, or None."""
    m = YEAR_RE.search(name)
    return m.group(0) if m else None


def _clean_stem(stem: str) -> str:
    """
    Normalise the filename stem:
    - strip leading whitespace / underscores
    - collapse runs of spaces
    - strip trailing whitespace
    """
    stem = LEADING_NOISE_RE.sub('', stem)
    stem = re.sub(r'  +', ' ', stem)
    return stem.strip()


def _pandoc_available() -> bool:
    return shutil.which('pandoc') is not None


def convert_file(docx_path: Path, dest_dir: Path, dest_stem: str | None = None,
                 dry_run: bool = False) -> Path | None:
    """
    Convert a single .docx to .md via pandoc.
    dest_stem: override the output filename stem (used when docx is a temp file).
    Returns the destination path, or None on failure.
    """
    stem = dest_stem if dest_stem else _safe_stem(docx_path.stem)
    dest_path = dest_dir / f'{stem}.md'

    if dry_run:
        print(f'  [dry-run] {docx_path.name!r} → {dest_path.relative_to(REPO_ROOT)}')
        return dest_path

    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            ['pandoc', str(docx_path), '-t', 'markdown', '-o', str(dest_path),
             '--wrap=none',              # no hard line wraps
             '--markdown-headings=atx',  # use # headings
             ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f'  ERROR converting {docx_path.name}: {result.stderr.strip()}')
            return None
        return dest_path
    except subprocess.TimeoutExpired:
        print(f'  TIMEOUT converting {docx_path.name}')
        return None
    except FileNotFoundError:
        print('  ERROR: pandoc not found. Install from https://pandoc.org/installing.html')
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main workflows
# ---------------------------------------------------------------------------

def _safe_stem(original_stem: str, max_len: int = 180) -> str:
    """
    Produce a filesystem-safe stem: strip leading noise, truncate so that
    full path stays under Windows MAX_PATH even in a deep temp dir.
    """
    stem = _clean_stem(original_stem)
    # Replace characters that are illegal on Windows
    stem = re.sub(r'[<>:"/\\|?*]', '-', stem)
    stem = stem[:max_len].rstrip('. ')
    return stem


def convert_zip(zip_path: Path, dry_run: bool = False) -> tuple[int, int, int]:
    """Extract zip entry-by-entry (to dodge Windows path limits), convert every
    .docx to .md.  Returns (ok, failed, skipped)."""
    if not zip_path.exists():
        print(f'Zip not found: {zip_path}')
        sys.exit(1)

    ok = failed = skipped = 0

    print(f'Reading {zip_path.name}...')
    with zipfile.ZipFile(zip_path) as zf:
        entries = [e for e in zf.infolist() if e.filename.endswith('.docx')]
        print(f'Found {len(entries)} .docx entries.\n')

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            for entry in entries:
                original_name = Path(entry.filename).stem
                safe_stem = _safe_stem(original_name)

                # Determine year from original filename or parent path component
                year = _find_year(original_name)
                if not year:
                    for part in Path(entry.filename).parts:
                        if YEAR_RE.fullmatch(part):
                            year = part
                            break
                if not year:
                    year = 'undated'

                dest_dir = DISCOURSES_DIR / year
                dest_md = dest_dir / f'{safe_stem}.md'

                if dest_md.exists() and dest_md.stat().st_size > 100:
                    print(f'  [skip] {dest_md.relative_to(REPO_ROOT)} (exists)')
                    skipped += 1
                    continue

                print(f'  {safe_stem[:80]}')

                if dry_run:
                    print(f'    → {dest_md.relative_to(REPO_ROOT)}')
                    ok += 1
                    continue

                # Extract to a short temp path to avoid Windows MAX_PATH
                idx = ok + failed + skipped
                tmp_docx = tmp_path / f'd{idx}.docx'
                try:
                    tmp_docx.write_bytes(zf.read(entry))
                except Exception as exc:
                    print(f'  ERROR extracting {entry.filename}: {exc}')
                    failed += 1
                    continue

                result = convert_file(tmp_docx, dest_dir, dest_stem=safe_stem, dry_run=False)
                if result:
                    ok += 1
                else:
                    failed += 1

    return ok, failed, skipped


def convert_dir(src_dir: Path, dry_run: bool = False) -> tuple[int, int, int]:
    """Convert all .docx in a directory tree. Returns (ok, failed, skipped)."""
    docx_files = sorted(src_dir.rglob('*.docx'))
    print(f'Found {len(docx_files)} .docx files in {src_dir}.\n')

    ok = failed = skipped = 0
    for docx in docx_files:
        year = _find_year(docx.stem) or 'undated'
        dest_dir = DISCOURSES_DIR / year
        dest_md = dest_dir / f'{_safe_stem(docx.stem)}.md'

        if dest_md.exists() and dest_md.stat().st_size > 100:
            print(f'  [skip] {dest_md.relative_to(REPO_ROOT)} (exists)')
            skipped += 1
            continue

        print(f'  {_safe_stem(docx.stem)[:80]}')
        result = convert_file(docx, dest_dir, dry_run=dry_run)
        if result:
            ok += 1
        else:
            failed += 1

    return ok, failed, skipped


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Convert .docx discourses to .md')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--zip', type=str, help='Path to zip archive containing .docx files')
    group.add_argument('--dir', type=str, help='Directory containing .docx files (recursive)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without writing files')
    args = parser.parse_args()

    if not _pandoc_available():
        print('ERROR: pandoc not found on PATH.')
        print('Install: https://pandoc.org/installing.html')
        sys.exit(1)

    if args.zip:
        zip_path = Path(args.zip)
        if not zip_path.is_absolute():
            zip_path = REPO_ROOT / zip_path
        ok, failed, skipped = convert_zip(zip_path, dry_run=args.dry_run)
    else:
        src_dir = Path(args.dir)
        if not src_dir.is_absolute():
            src_dir = REPO_ROOT / src_dir
        ok, failed, skipped = convert_dir(src_dir, dry_run=args.dry_run)

    print(f'\n{"="*60}')
    action = '[dry-run] would convert' if args.dry_run else 'converted'
    print(f'Done. {action}: {ok}  |  failed: {failed}  |  skipped: {skipped}')
    print(f'Output directory: discourses/<year>/')


if __name__ == '__main__':
    main()

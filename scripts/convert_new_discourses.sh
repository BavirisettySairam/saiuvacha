#!/bin/bash
# Convert new .docx discourse files to .md and place in discourses/<year>/
# Skips files that already exist as .md in the target folder.

RAW_DIR="discourses/raw/update_21.04"
OUT_BASE="discourses"

new=0
skipped=0
failed=0

for docx in "$RAW_DIR"/**/*.docx; do
    year=$(basename "$(dirname "$docx")")
    stem=$(basename "$docx" .docx)
    out_dir="$OUT_BASE/$year"
    out_file="$out_dir/$stem.md"

    mkdir -p "$out_dir"

    if [ -f "$out_file" ]; then
        echo "[skip] $stem"
        ((skipped++))
        continue
    fi

    pandoc "$docx" -f docx -t markdown --wrap=none -o "$out_file" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "[ok]   $stem"
        ((new++))
    else
        echo "[FAIL] $stem"
        ((failed++))
    fi
done

echo ""
echo "Done: $new new, $skipped skipped, $failed failed"

#!/bin/bash
set -u

TEST_URL="${1:-https://www.youtube.com/watch?v=jNQXAC9IVRw}"

WORKDIR=$(mktemp -d)
cd "$WORKDIR" || exit 1

echo "=============================================================="
echo "Target URL: $TEST_URL"
echo "Work dir:   $WORKDIR"
echo "=============================================================="

echo ""
echo "=== STEP 1: actually download the auto-caption (English), skip video ==="
yt-dlp --write-auto-sub --sub-lang en --skip-download --sub-format vtt \
-o "caption" "$TEST_URL" 2>&1

echo ""
echo "=== STEP 2: files produced in work dir ==="
ls -la "$WORKDIR"

CAPTION_FILE=$(find "$WORKDIR" -iname "*.vtt" | head -1)

if [ -z "$CAPTION_FILE" ]; then
    echo ""
    echo "RESULT: FAIL -- no .vtt caption file was produced"
    exit 1
fi

echo ""
echo "=== STEP 3: raw caption file, first 30 lines ==="
head -30 "$CAPTION_FILE"

echo ""
echo "=== STEP 4: raw file size ==="
wc -l "$CAPTION_FILE"
wc -c "$CAPTION_FILE"

echo ""
echo "=== STEP 5: clean plain text ==="
grep -v -E '^WEBVTT|^Kind:|^Language:|^[0-9]+$|-->' "$CAPTION_FILE" \
| sed -E 's/<[^>]+>//g' \
| sed '/^[[:space:]]*$/d' \
| awk '!seen[$0]++' \
> "$WORKDIR/clean_text.txt"

cat "$WORKDIR/clean_text.txt"

echo ""
echo "=== STEP 6: cleaned text stats + PASS/FAIL judgment ==="
WORD_COUNT=$(wc -w < "$WORKDIR/clean_text.txt")
LINE_COUNT=$(wc -l < "$WORKDIR/clean_text.txt")
echo "words=$WORD_COUNT lines=$LINE_COUNT"

if [ "$WORD_COUNT" -gt 5 ]; then
    echo "RESULT: PASS -- caption content successfully extracted into readable text ($WORD_COUNT words)"
else
    echo "RESULT: FAIL -- cleaned text is too sparse/empty ($WORD_COUNT words)"
fi

echo ""
echo "=============================================================="
echo "Work dir left at: $WORKDIR"
echo "=============================================================="

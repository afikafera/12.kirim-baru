#!/bin/bash

# READ-ONLY diagnostic for the subtitle HTTP 429 on the ACR candidate video.
# No proxy, no IP rotation, no rate-limit bypass.
# Tests are deliberately spaced out to avoid hammering YouTube.

set -u

URL="https://www.youtube.com/watch?v=_S3i-Br-sqY"
PAUSE=8

WORKDIR=$(mktemp -d)
cd "$WORKDIR" || exit 1

echo "Work dir: $WORKDIR"
echo "Target:   $URL"
echo ""

echo "=============================================================="
echo "SECTION 0 -- full --list-subs (automatic AND manual sections)"
echo "=============================================================="

yt-dlp --list-subs --skip-download "$URL" 2>&1
sleep "$PAUSE"

echo ""
echo "=============================================================="
echo "SECTION A/B -- try each subtitle FORMAT for English auto-caption"
echo "=============================================================="

for FMT in vtt srv3 json3 ttml srv1; do
    echo ""
    echo "--- format=$FMT ---"

    yt-dlp \
        --write-auto-sub \
        --sub-lang en \
        --skip-download \
        --sub-format "$FMT" \
        -o "fmt_${FMT}" \
        "$URL" 2>&1 | tail -15

    sleep "$PAUSE"
done

echo ""
echo "=============================================================="
echo "SECTION C -- try MANUAL subtitle (any language) if one exists"
echo "=============================================================="

yt-dlp \
    --write-sub \
    --sub-lang all \
    --skip-download \
    --sub-format vtt \
    -o "manual" \
    "$URL" 2>&1 | tail -20

sleep "$PAUSE"

echo ""
echo "=============================================================="
echo "SECTION D -- try different YouTube player clients"
echo "=============================================================="

for CLIENT in android web_safari tv_embedded ios; do
    echo ""
    echo "--- player_client=$CLIENT ---"

    yt-dlp \
        --extractor-args "youtube:player_client=$CLIENT" \
        --write-auto-sub \
        --sub-lang en \
        --skip-download \
        --sub-format vtt \
        -o "client_${CLIENT}" \
        "$URL" 2>&1 | tail -15

    sleep "$PAUSE"
done

echo ""
echo "=============================================================="
echo "SECTION E -- verbose run"
echo "=============================================================="

yt-dlp \
    -v \
    --write-auto-sub \
    --sub-lang en \
    --skip-download \
    --sub-format vtt \
    -o "verbose_run" \
    "$URL" 2>&1 \
    | grep -i -E \
        "po.?token|js.?runtime|nsig|player_client|WARNING|ERROR|429" \
    | head -40

sleep "$PAUSE"

echo ""
echo "=============================================================="
echo "SECTION F(1) -- polite pacing"
echo "=============================================================="

yt-dlp \
    --sleep-requests 3 \
    --sleep-subtitles 5 \
    --write-auto-sub \
    --sub-lang en \
    --skip-download \
    --sub-format vtt \
    -o "paced" \
    "$URL" 2>&1 | tail -20

sleep "$PAUSE"

echo ""
echo "=============================================================="
echo "SECTION F(2) -- transient vs persistent"
echo "=============================================================="

echo "Waiting an additional 30 seconds before final retry..."
sleep 30

yt-dlp \
    --write-auto-sub \
    --sub-lang en \
    --skip-download \
    --sub-format vtt \
    -o "retry_after_wait" \
    "$URL" 2>&1 | tail -20

echo ""
echo "=============================================================="
echo "SUMMARY -- files actually produced"
echo "=============================================================="

find "$WORKDIR" -type f \( \
    -name "*.vtt" -o \
    -name "*.srv*" -o \
    -name "*.json3" -o \
    -name "*.ttml" \
\) 2>/dev/null |
while read -r f; do
    echo "  $f  ($(wc -c < "$f") bytes)"
done

echo ""
echo "Work dir left at: $WORKDIR"
echo "Delete when done: rm -rf $WORKDIR"

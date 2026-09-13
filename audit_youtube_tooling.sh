#!/bin/bash
# AUDIT ONLY -- read-only capability check for YouTube content acquisition.
# Does NOT install, modify, or configure anything.
# Does NOT print any API key value -- only whether one appears to be set.

echo "=============================================================="
echo "A. yt-dlp"
echo "=============================================================="
if command -v yt-dlp >/dev/null 2>&1; then
    echo "AVAILABLE: $(yt-dlp --version 2>&1)"
else
    echo "NOT AVAILABLE"
fi

echo ""
echo "=============================================================="
echo "B. ffmpeg"
echo "=============================================================="
if command -v ffmpeg >/dev/null 2>&1; then
    echo "AVAILABLE: $(ffmpeg -version 2>&1 | head -1)"
else
    echo "NOT AVAILABLE"
fi

echo ""
echo "=============================================================="
echo "C. ffprobe"
echo "=============================================================="
if command -v ffprobe >/dev/null 2>&1; then
    echo "AVAILABLE: $(ffprobe -version 2>&1 | head -1)"
else
    echo "NOT AVAILABLE"
fi

echo ""
echo "=============================================================="
echo "JS runtime for YouTube (yt-dlp needs this per agent-reach's own"
echo "YouTubeChannel.check() logic -- YouTube's anti-bot JS challenge)"
echo "=============================================================="
if command -v deno >/dev/null 2>&1; then
    echo "AVAILABLE: deno $(deno --version 2>&1 | head -1)"
elif command -v node >/dev/null 2>&1; then
    echo "AVAILABLE BUT NOT SUITABLE ALONE: node $(node --version 2>&1) (needs explicit --js-runtimes config per agent-reach's youtube.py)"
else
    echo "NOT AVAILABLE (deno or node required for YouTube to work reliably with yt-dlp)"
fi

echo ""
echo "=============================================================="
echo "D. yt-dlp subtitle/caption listing capability (live test, no download)"
echo "   Using a known stable public video as a neutral test target."
echo "=============================================================="
if command -v yt-dlp >/dev/null 2>&1; then
    yt-dlp --list-subs --skip-download "https://www.youtube.com/watch?v=jNQXAC9IVRw" 2>&1 | head -30
else
    echo "SKIPPED (yt-dlp not available)"
fi

echo ""
echo "=============================================================="
echo "E. Any dedicated YouTube transcript/caption library already installed"
echo "=============================================================="
python3 -m pip list 2>/dev/null | grep -iE "youtube.transcript|youtube.dl|pytube|yt.dlp" || echo "NONE FOUND matching youtube-transcript/pytube/yt-dlp pip packages"

echo ""
echo "=============================================================="
echo "F. Local Whisper / whisper.cpp / faster-whisper or equivalent"
echo "=============================================================="
echo "-- pip packages --"
python3 -m pip list 2>/dev/null | grep -iE "whisper|faster.whisper" || echo "NONE FOUND (openai-whisper / faster-whisper not in pip list)"
echo "-- python import test (openai-whisper) --"
python3 -c "import whisper; print('AVAILABLE: whisper module importable, version', getattr(whisper,'__version__','unknown'))" 2>&1 | tail -1
echo "-- python import test (faster-whisper) --"
python3 -c "import faster_whisper; print('AVAILABLE: faster_whisper module importable')" 2>&1 | tail -1
echo "-- whisper.cpp binary search (common binary names) --"
for bin in whisper.cpp whisper-cpp main whisper; do
    if command -v "$bin" >/dev/null 2>&1; then
        echo "found candidate binary: $bin -> $(command -v $bin)"
    fi
done
echo "-- GPU availability (relevant if local Whisper is considered later) --"
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1
else
    echo "no nvidia-smi found (CPU-only inference would apply if local Whisper is ever used)"
fi

echo ""
echo "=============================================================="
echo "G. Groq/OpenAI provider configuration status (existence only, NEVER printing the key value)"
echo "=============================================================="
echo "-- environment variables --"
for var in GROQ_API_KEY OPENAI_API_KEY; do
    val="${!var}"
    if [ -n "$val" ]; then
        echo "$var: SET (length=${#val} chars, value not shown)"
    else
        echo "$var: NOT SET in current shell env"
    fi
done

echo ""
echo "-- agent-reach's own doctor command (sanctioned diagnostic, should not leak secrets) --"
if command -v agent-reach >/dev/null 2>&1; then
    agent-reach doctor 2>&1
else
    echo "agent-reach CLI not found on PATH -- trying python -m invocation"
    cd ~/research-assistant/agent-reach 2>/dev/null && python3 -m agent_reach.cli doctor 2>&1
fi

echo ""
echo "=============================================================="
echo "AUDIT COMPLETE -- no installs, no config changes, no secrets printed"
echo "=============================================================="

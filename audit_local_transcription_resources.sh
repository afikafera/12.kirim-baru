#!/bin/bash
# AUDIT ONLY -- read-only resource check for local transcription
# feasibility. Does NOT install, modify, or download anything.

echo "=============================================================="
echo "CPU"
echo "=============================================================="
echo "-- core count --"
nproc 2>&1 || echo "nproc not available"
echo "-- model name --"
grep -m1 "model name" /proc/cpuinfo 2>&1 || echo "cpuinfo not readable"
echo "-- AVX2/AVX512 support (faster-whisper/whisper.cpp perform much better with these) --"
grep -m1 -o -E "avx2|avx512f" /proc/cpuinfo 2>&1 || echo "no AVX2/AVX512 flags found"

echo ""
echo "=============================================================="
echo "RAM"
echo "=============================================================="
free -h 2>&1 || echo "free not available"

echo ""
echo "=============================================================="
echo "DISK (relevant for downloading a local Whisper model, e.g."
echo "small=~500MB, medium=~1.5GB, large-v3=~3GB)"
echo "=============================================================="
df -h ~/research-assistant 2>&1

echo ""
echo "=============================================================="
echo "GPU (re-check, in case CUDA toolkit/driver details matter for sizing)"
echo "=============================================================="
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi 2>&1
else
    echo "no nvidia-smi -- CPU-only inference would apply"
fi

echo ""
echo "=============================================================="
echo "Existing model cache directories (would indicate a local engine"
echo "was already used/downloaded before, without us installing anything)"
echo "=============================================================="
for d in ~/.cache/whisper ~/.cache/huggingface ~/.cache/faster_whisper; do
    if [ -d "$d" ]; then
        echo "FOUND: $d ($(du -sh "$d" 2>/dev/null | cut -f1))"
    else
        echo "not present: $d"
    fi
done

echo ""
echo "=============================================================="
echo "AUDIT COMPLETE -- no installs, no downloads, no config changes"
echo "=============================================================="

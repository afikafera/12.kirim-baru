"""
VERIFY: production-shaped caption acquisition function with explicit
status handling (SUCCESS / NO_CAPTION / HTTP_429 / EXTRACTION_ERROR).

This is the exact candidate for what would eventually be added to
aran_search/searcher.py's fetch_url() -- tested here in isolation first,
not yet wired into production.

Tests three cases:
  1. Neutral video (known --list-subs worked earlier) -- IMPORTANT
     control: confirms whether SUCCESS is reachable at all right now,
     and whether 429 is specific to the ACR candidate or affects
     caption downloads generally from this server right now.
  2. ACR candidate video -- known to 429 (already proven).
  3. A deliberately invalid video ID -- expect EXTRACTION_ERROR.

No install, no production file touched.

Run from anywhere with python3 + yt-dlp on PATH:
    python3 verify_caption_acquisition_states.py
"""
import glob
import os
import re
import subprocess
import tempfile


def acquire_youtube_caption(url: str, lang: str = "en", timeout: int = 30) -> dict:
    """Attempt to acquire a YouTube caption as clean plain text.

    Returns:
        {"status": "SUCCESS" | "NO_CAPTION" | "HTTP_429" | "EXTRACTION_ERROR",
         "content": str or None,
         "detail": str}
    """
    with tempfile.TemporaryDirectory() as workdir:
        out_template = os.path.join(workdir, "caption")
        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    "--write-auto-sub", "--sub-lang", lang,
                    "--skip-download", "--sub-format", "vtt",
                    "-o", out_template, url,
                ],
                capture_output=True, text=True, timeout=timeout,
            )
            combined = (result.stdout or "") + (result.stderr or "")
        except subprocess.TimeoutExpired:
            return {"status": "EXTRACTION_ERROR", "content": None, "detail": "yt-dlp timed out"}
        except FileNotFoundError:
            return {"status": "EXTRACTION_ERROR", "content": None, "detail": "yt-dlp not found on PATH"}

        low = combined.lower()

        if "429" in combined or "too many requests" in low:
            return {"status": "HTTP_429", "content": None, "detail": combined[-500:]}

        vtt_files = glob.glob(os.path.join(workdir, "*.vtt"))

        if not vtt_files:
            no_caption_markers = (
                "no automatic captions",
                "no subtitles",
                "requested format is not available",
                "video doesn't have subtitles",
            )
            if any(m in low for m in no_caption_markers):
                return {"status": "NO_CAPTION", "content": None, "detail": combined[-500:]}
            return {"status": "EXTRACTION_ERROR", "content": None, "detail": combined[-500:]}

        with open(vtt_files[0], encoding="utf-8", errors="replace") as f:
            raw = f.read()

        clean_lines = []
        seen = set()
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
                continue
            if line.isdigit():
                continue
            if "-->" in line:
                continue
            line = re.sub(r"<[^>]+>", "", line)
            if line and line not in seen:
                seen.add(line)
                clean_lines.append(line)

        text = "\n".join(clean_lines)

        if len(text.split()) < 5:
            return {"status": "NO_CAPTION", "content": None, "detail": "caption file present but essentially empty after cleaning"}

        return {"status": "SUCCESS", "content": text, "detail": f"{len(text.split())} words extracted"}


TEST_CASES = [
    ("Neutral video (control -- was successfully listed earlier)",
     "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    ("ACR candidate (known 429 from prior diagnostic)",
     "https://www.youtube.com/watch?v=_S3i-Br-sqY"),
    ("Deliberately invalid video ID (expect EXTRACTION_ERROR)",
     "https://www.youtube.com/watch?v=THIS_ID_DOES_NOT_EXIST"),
]

if __name__ == "__main__":
    for label, url in TEST_CASES:
        print("=" * 90)
        print(f"{label}")
        print(f"URL: {url}")
        print("=" * 90)
        outcome = acquire_youtube_caption(url)
        print(f"STATUS: {outcome['status']}")
        if outcome["status"] == "SUCCESS":
            preview = outcome["content"][:300]
            print(f"DETAIL: {outcome['detail']}")
            print(f"CONTENT PREVIEW (first 300 chars):\n{preview}")
        else:
            print(f"DETAIL (last 500 chars of yt-dlp output):\n{outcome['detail']}")
        print()

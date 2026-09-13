import subprocess
import json
import re

def scrape_tiktok_url(url: str) -> dict:
    """Scrape info video TikTok dari URL."""
    try:
        # Download halaman
        result = subprocess.run(
            ["curl", "-s", "-L", "-A", "Mozilla/5.0", url],
            capture_output=True, text=True, timeout=15
        )
        html = result.stdout

        # Cari JSON data di script tag
        match = re.search(r'"propsPageProps":({.*?})', html)
        if match:
            try:
                data = json.loads(match.group(1))
                video = data.get("itemInfo", {}).get("itemStruct", {})
                return {
                    "title": video.get("desc", ""),
                    "author": video.get("author", {}).get("uniqueId", ""),
                    "views": video.get("stats", {}).get("playCount", 0),
                    "likes": video.get("stats", {}).get("diggCount", 0),
                    "url": url
                }
            except:
                pass

        return {"error": "Tidak bisa parse data TikTok", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}

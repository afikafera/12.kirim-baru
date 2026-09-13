import re
import httpx
from bs4 import BeautifulSoup
from .base import BaseConnector, Document


class DiscourseConnector(BaseConnector):

    # Pola URL Discourse: /t/slug/id atau /t/id
    PATTERN = re.compile(r'/t/(?:[^/]+/)?(\d+)')

    def detect(self, url: str) -> bool:
        return bool(self.PATTERN.search(url))

    def _extract_id(self, url: str) -> str:
        m = self.PATTERN.search(url)
        return m.group(1) if m else None

    def _extract_base(self, url: str) -> str:
        return url.split('/t/')[0]

    def _strip_html(self, html: str) -> str:
        soup = BeautifulSoup(html, 'html.parser')
        return soup.get_text(separator=' ', strip=True)

    def fetch(self, url: str) -> Document:
        # Cache hit?
        cached = self._cache_get(url)
        if cached:
            return cached

        tid = self._extract_id(url)
        if not tid:
            return Document(title="Error", source_url=url, platform="discourse")

        base = self._extract_base(url)
        json_url = f"{base}/t/{tid}.json"

        try:
            resp = httpx.get(json_url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            # Error dari Discourse?
            if "errors" in data:
                return Document(
                    title="Error",
                    source_url=url,
                    platform="discourse",
                    metadata={"error": data["errors"]}
                )

            posts = []
            participants = []
            seen = set()

            for p in data.get("post_stream", {}).get("posts", []):
                username = p.get("username", "unknown")
                post = {
                    "number": p.get("post_number", 0),
                    "author": username,
                    "created_at": p.get("created_at", ""),
                    "reply_to": p.get("reply_to_post_number"),
                    "content": self._strip_html(p.get("cooked", ""))[:2000],
                }
                posts.append(post)

                if username not in seen:
                    seen.add(username)
                    participants.append(username)

            doc = Document(
                title=data.get("title", ""),
                source_url=url,
                platform="discourse",
                author=posts[0]["author"] if posts else "",
                created_at=data.get("created_at", ""),
                messages=posts,
                participants=participants,
                metadata={
                    "total_posts": len(posts),
                    "reply_count": data.get("reply_count", 0),
                    "last_activity": data.get("last_posted_at", ""),
                    "solved": "solved" in [t.lower() for t in data.get("tags", [])],
                }
            )

            self._cache_set(url, doc)
            return doc

        except Exception as e:
            return Document(
                title="Error",
                source_url=url,
                platform="discourse",
                metadata={"error": str(e)}
            )

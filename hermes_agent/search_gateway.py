import json
import logging
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


class _DDGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._current = None
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "a" and "result__a" in attrs.get("class", ""):
            self._current = {
                "title": "",
                "url": attrs.get("href", ""),
                "content": "",
            }
            self._in_title = True

        elif self._current and tag in ("a", "div"):
            cls = attrs.get("class", "")
            if "result__snippet" in cls:
                self._in_snippet = True

    def handle_data(self, data):
        if not self._current:
            return

        if self._in_title:
            self._current["title"] += data

        if self._in_snippet:
            self._current["content"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._current and self._in_title:
            self._in_title = False

            if self._current["title"].strip():
                self.results.append(self._current)

        if tag == "div":
            self._in_snippet = False


class SearchGateway:
    """
    Isolated search-engine gateway.

    Priority:
        1. DuckDuckGo direct
        2. SearXNG fallback

    Search ranking belongs here, not in Hermes Core.
    """

    DDG_URL = "https://html.duckduckgo.com/html/"
    SEARXNG_URL = "http://localhost:8888/search"

    DDG_LIMIT = 10
    SEARXNG_LIMIT = 10

    def __init__(self):
        self.last_engine = None

    # ---------------------------------------------------------
    # DuckDuckGo
    # ---------------------------------------------------------

    def search_duckduckgo(self, query: str, limit: int = DDG_LIMIT) -> list:
        try:
            data = urllib.parse.urlencode({"q": query}).encode()

            request = urllib.request.Request(
                self.DDG_URL,
                data=data,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 "
                        "(KHTML, like Gecko) "
                        "Chrome/131.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.7",
                    "Referer": "https://html.duckduckgo.com/",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "same-origin",
                    "Sec-Fetch-User": "?1",
                },
            )

            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8", errors="replace")

            if "challenge-form" in body.lower():
                logger.warning(
                    "[SEARCH GATEWAY] DDG CAPTCHA query=%r",
                    query,
                )
                return []

            parser = _DDGParser()
            parser.feed(body)

            results = parser.results[:limit]

            logger.info(
                "[SEARCH GATEWAY] DDG query=%r results=%d",
                query,
                len(results),
            )

            return results

        except Exception:
            logger.exception(
                "[SEARCH GATEWAY] DDG failed query=%r",
                query,
            )
            return []

    # ---------------------------------------------------------
    # SearXNG fallback
    # ---------------------------------------------------------

    def search_searxng(self, query: str, limit: int = SEARXNG_LIMIT) -> list:
        try:
            params = urllib.parse.urlencode({
                "q": query,
                "format": "json",
                "categories": "general",
            })

            request = urllib.request.Request(
                f"{self.SEARXNG_URL}?{params}",
                headers={
                    "User-Agent": "Hermes-Research-Assistant/1.0",
                },
            )

            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(
                    response.read().decode("utf-8", errors="replace")
                )

            results = data.get("results", [])[:limit]

            logger.info(
                "[SEARCH GATEWAY] SearXNG query=%r results=%d",
                query,
                len(results),
            )

            return results

        except Exception:
            logger.exception(
                "[SEARCH GATEWAY] SearXNG failed query=%r",
                query,
            )
            return []

    # ---------------------------------------------------------
    # Relevance
    # ---------------------------------------------------------

    def _relevance(self, query: str, result: dict) -> int:
        text = (
            f"{result.get('title', '')} "
            f"{result.get('content', '')}"
        ).lower()

        tokens = [
            x for x in re.findall(r"[a-zA-Z0-9]+", query.lower())
            if len(x) > 2
        ]

        return sum(
            1 for token in tokens
            if re.search(
                rf"(?<![a-zA-Z0-9]){re.escape(token)}(?![a-zA-Z0-9])",
                text,
            )
        )

    def rank(self, query: str, results: list, limit: int = 10) -> list:
        ranked = []

        for result in results:
            score = self._relevance(query, result)

            if score <= 0:
                continue

            item = dict(result)
            item["_search_score"] = score
            ranked.append(item)

        ranked.sort(
            key=lambda x: x["_search_score"],
            reverse=True,
        )

        return ranked[:limit]

    # ---------------------------------------------------------
    # Main gateway
    # ---------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> list:
        logger.info(
            "[SEARCH GATEWAY] START query=%r",
            query,
        )

        # DDG removed from the active search path.
        # SearXNG is the sole gateway search backend.
        searx_raw = self.search_searxng(query)

        # Some verbose queries return no SearXNG results.
        # Retry once using the core subject terms.
        if not searx_raw:
            tokens = re.findall(r"[A-Za-z0-9]+", query.lower())
            stopwords = {
                "official", "documentation", "document", "specification",
                "behavior", "handling", "examples", "example",
                "version", "compatibility", "and", "the", "for",
            }
            core = [
                token for token in tokens
                if len(token) > 2 and token not in stopwords
            ]
            fallback_query = " ".join(core[:4])

            if fallback_query and fallback_query.lower() != query.lower():
                logger.info(
                    "[SEARCH GATEWAY] SEARXNG RETRY "
                    "original=%r fallback=%r",
                    query,
                    fallback_query,
                )
                searx_raw = self.search_searxng(fallback_query)

        searx = self.rank(
            query,
            searx_raw,
            limit,
        )

        self.last_engine = "searxng"

        logger.info(
            "[SEARCH GATEWAY] FALLBACK engine=searxng "
            "query=%r results=%d",
            query,
            len(searx),
        )

        return searx

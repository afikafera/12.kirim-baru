import subprocess
import json
import urllib.parse
from urllib.parse import urlparse
import logging
import asyncio

from aran_search.fetch_result import (
    FetchClass,
    classify_fetch_result,
    split_http_status,
    validate_github_response,
)
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AgentReachSearcher:

    ENABLE_QUERY_REFINEMENT = False

    BLOCKED = ["scribd.com", "coursehero.com", "slideshare.net", "pinterest.com"]

    SUBDOMAIN_RULES = {
        "docs": 3, "help": 3, "wiki": 2, "forum": 3, "community": 2,
    }

    DOMAIN_RULES = [
        ("reddit.com", 3), ("stackexchange.com", 3), ("stackoverflow.com", 3),
        ("askubuntu.com", 3), ("serverfault.com", 3), ("superuser.com", 3),
        ("github.com", 3), ("baeldung.com", 3), ("kaskus.co.id", 2),
        ("youtube.com", 2), ("vimeo.com", 1),
        ("twitter.com", 1), ("x.com", 1), ("tiktok.com", 1),
        ("instagram.com", 1), ("facebook.com", 1), ("linkedin.com", 1),
    ]

    DEFAULT_CATEGORY_GROUPS = [
        ("general,it", 20, 3),
    ]

    UPSTREAM_PRIORITY = [
        "google cse",
        "duckduckgo",
        "searxng",
    ]

    UPSTREAMS = (
        ("duckduckgo", 10),
    )

    VIDEO_CATEGORY_GROUP = ("videos", 8, 1)
    SOCIAL_CATEGORY_GROUP = ("social+media", 8, 1)

    def __init__(self, llm_analyzer=None, refine_queries=None):
        self.llm = llm_analyzer
        self.refine_queries = (
            self.ENABLE_QUERY_REFINEMENT
            if refine_queries is None
            else bool(refine_queries)
        )

    def _run_async_sync(self, coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        def runner():
            return asyncio.run(coro)

        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(runner).result()

    def _refine_query(self, query: str) -> str:
        if not self.llm or not self.refine_queries:
            return query
        prompt = f"""Perbaiki query berikut agar lebih efektif untuk web search.
Tambahkan kata kunci relevan. JANGAN gunakan site: filter.
JANGAN mengarang pesan error. Return HANYA query yang sudah diperbaiki.

Query: {query}"""
        try:
            result = self.llm.analyze(
                "Kamu search query optimizer. Return hanya optimized query.",
                prompt, temperature=0.1
            )
            refined = result["content"].strip().strip('"').strip("`")
            if len(refined) > 10:
                return refined
            return query
        except:
            return query

    def _score_url(self, url: str) -> int:
        try:
            netloc = urlparse(url).netloc.lower()
            parts = netloc.split(".")
            if len(parts) > 2 and parts[0] in self.SUBDOMAIN_RULES:
                return self.SUBDOMAIN_RULES[parts[0]]
            for domain, points in self.DOMAIN_RULES:
                if netloc == domain or netloc.endswith("." + domain):
                    return points
        except:
            pass
        return 0

    def _fetch_engine(self, query: str, engine: str, limit: int) -> list:
        """Fetch one explicit upstream through the local SearXNG instance."""
        try:
            result = subprocess.run(
                [
                    "curl", "-sG",
                    "http://localhost:8888/search",
                    "--data-urlencode", f"q={query}",
                    "--data-urlencode", "format=json",
                    "--data-urlencode", f"engines={engine}",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )

            data = json.loads(result.stdout or "{}")
            return data.get("results", [])[:limit]

        except Exception:
            logger.exception(
                "[FETCH ENGINE] failed engine=%s query=%s",
                engine,
                query,
            )
            return []

    def _fetch_category(self, query: str, categories: str, limit: int) -> list:
        try:
            q = urllib.parse.quote(query)
            engines = ",".join(engine for engine, _ in self.UPSTREAMS)

            result = subprocess.run(
                [
                    "curl", "-s",
                    f"http://localhost:8888/search"
                    f"?q={q}"
                    f"&format=json"
                    f"&categories={categories}"
                    f"&engines={urllib.parse.quote(engines)}",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )

            return json.loads(result.stdout).get("results", [])[:limit]

        except Exception:
            logger.exception(
                "[FETCH CATEGORY] failed categories=%s",
                categories,
            )
            return []

    def _score_and_rank(self, results: list, max_output: int, category_label: str = "") -> list:
        import re

        raw_query = getattr(self, "_active_query", "")
        query = raw_query.lower()

        stopwords = {
            "dan", "di", "ke", "dari", "untuk", "dengan", "yang",
            "ini", "itu", "the", "a", "an", "of", "in", "on", "at",
            "to", "for", "with", "by", "from", "and",
            "spesifikasi", "specification", "specifications",
            "review", "harga", "price", "beli", "buy"
        }

        query_tokens = [
            token.lower()
            for token in re.findall(
                r"[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)+|[a-zA-Z0-9]+",
                query,
            )
            if len(token) > 1 and token not in stopwords
        ]

        scored = []

        for r in results:
            url = r.get("url", "")
            netloc = urlparse(url).netloc.lower()

            if any(d in netloc for d in self.BLOCKED):
                continue

            title = r.get("title", "")
            content = r.get("content", "")
            haystack = f"{title} {content}".lower()

            def token_present(token: str) -> bool:
                return bool(
                    re.search(
                        rf"(?<![a-zA-Z0-9]){re.escape(token)}(?![a-zA-Z0-9])",
                        haystack,
                    )
                )

            matches = sum(token_present(token) for token in query_tokens)

            entity_match = (
                bool(query_tokens)
                and all(token_present(token) for token in query_tokens)
            )

            raw_tokens = re.findall(
                r"[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)+|[a-zA-Z0-9]+",
                raw_query,
            )
            anchor_tokens = [
                token.lower()
                for token in raw_tokens
                if (
                    any(char.isdigit() for char in token)
                    or token.isupper()
                    or (
                        any(char.isupper() for char in token[1:])
                        and any(char.islower() for char in token)
                    )
                )
                and token.lower() in query_tokens
            ]

            if anchor_tokens:
                if not all(token_present(token) for token in anchor_tokens):
                    continue
            elif query_tokens:
                if matches < min(2, len(query_tokens)):
                    continue

            matched_tokens = [t for t in query_tokens if token_present(t)]
            logger.info(
                "[AUDIT SEARCH GATE] category=%s url=%s matches=%d matched=%s entity_match=%s",
                category_label, url, matches, matched_tokens, entity_match,
            )

            base_score = float(r.get("score", 0) or 0)
            relevance_bonus = matches * 2.0
            entity_bonus = 5.0 if entity_match else 0.0

            official_bonus = (
                3.0
                if netloc == "acrspeaker.com"
                or netloc.endswith(".acrspeaker.com")
                else 0.0
            )

            domain_bonus = self._score_url(url) * 0.1

            engine = r.get("engine", "")
            engine_bonus = (
                0.1
                if engine in ["google cse", "brave", "duckduckgo"]
                else 0.0
            )

            score = (
                base_score
                + relevance_bonus
                + entity_bonus
                + official_bonus
                + domain_bonus
                + engine_bonus
            )

            scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)

        seen = set()
        top = []

        for score, r in scored:
            netloc = urlparse(r.get("url", "")).netloc.lower()

            if netloc in seen:
                continue

            seen.add(netloc)
            top.append((score, r))

            if len(top) >= max_output:
                break

        return top

    def _has_sufficient_upstream_results(self, ranked: list) -> bool:
        """
        Stop upstream cascade only when results are genuinely usable.

        A result from social/video domains alone is not sufficient.
        One official/non-social result is sufficient.
        Otherwise require at least two non-social results.
        """
        if not ranked:
            return False

        social_hosts = (
            "instagram.com",
            "facebook.com",
            "tiktok.com",
            "youtube.com",
            "x.com",
            "twitter.com",
        )

        non_social = []

        for score, result in ranked:
            url = result.get("url", "").lower()
            if not any(host in url for host in social_hosts):
                non_social.append(result)

        # One solid non-social result is enough to stop.
        if len(non_social) >= 1:
            return True

        # Social/video-only results must never stop the cascade.
        return False

    def search_searxng(
        self,
        query: str,
        allow_video: bool = False,
        allow_social: bool = False,
    ) -> str:
        try:
            refined = self._refine_query(query)
            self._active_query = refined

            for engine, fetch_limit in self.UPSTREAMS:
                raw = self._fetch_engine(refined, engine, fetch_limit)
                ranked = self._score_and_rank(raw, 5, engine)

                logger.info(
                    "[UPSTREAM CASCADE] engine=%s raw=%d relevant=%d",
                    engine, len(raw), len(ranked)
                )

                if self._has_sufficient_upstream_results(ranked):
                    out = ""
                    for score, r in ranked[:5]:
                        title = r.get("title", "")
                        url = r.get("url", "")
                        content = r.get("content", "")[:150]
                        source_engine = r.get("engine", engine)
                        out += (
                            f"- [{source_engine}] {title}\n"
                            f"  {content}\n"
                            f"  {url}\n"
                        )
                    return out or "Tidak ada hasil relevan"

            all_top = []
            category_groups = list(self.DEFAULT_CATEGORY_GROUPS)

            if allow_video:
                category_groups.append(self.VIDEO_CATEGORY_GROUP)

            if allow_social:
                category_groups.append(self.SOCIAL_CATEGORY_GROUP)

            for categories, fetch_limit, output_slots in category_groups:
                raw = self._fetch_category(refined, categories, fetch_limit)
                ranked = self._score_and_rank(raw, output_slots, categories)
                all_top.extend(ranked)

            all_top.sort(key=lambda x: x[0], reverse=True)

            out = ""
            for score, r in all_top[:5]:
                title = r.get("title", "")
                url = r.get("url", "")
                content = r.get("content", "")[:150]
                engine = r.get("engine", "")
                out += f"- [{engine}] {title}\n  {content}\n  {url}\n"

            return out or "Tidak ada hasil relevan"

        except Exception:
            logger.exception("[search_searxng] failed")
            return "Error search"

    def _format_discourse(self, doc) -> str:
        out = f"""
[FORUM DISCOURSE]
Judul: {doc.title}
Penulis: {doc.author}
Total Post: {doc.metadata.get('total_posts', 0)}
Partisipan: {', '.join(doc.participants)}
Status: {'SOLVED' if doc.metadata.get('solved') else 'Belum solved'}

"""
        for msg in doc.messages:
            reply_info = f" (balasan ke post #{msg['reply_to']})" if msg.get('reply_to') else ""
            out += f"--- Post #{msg['number']} oleh {msg['author']}{reply_info} ---\n{msg['content']}\n\n"
        return out

    def _inspect_dom(self, url: str):
        """
        Inspeksi DOM untuk mendeteksi wrapper same-origin iframe.
        Belum mengubah perilaku fetch_url().
        """
        try:
            import requests
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin, urlparse

            r = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )

            soup = BeautifulSoup(r.text, "html.parser")

            info = {
                "status": r.status_code,
                "html_len": len(r.text),
                "body_len": len(soup.get_text(" ", strip=True)),
                "iframe_count": 0,
                "same_origin_iframe": False,
                "iframe_src": None,
            }

            origin = urlparse(url).netloc

            for frame in soup.find_all(["iframe", "frame"]):
                src = frame.get("src")
                if not src:
                    continue

                info["iframe_count"] += 1
                full = urljoin(url, src)

                if urlparse(full).netloc == origin:
                    info["same_origin_iframe"] = True
                    info["iframe_src"] = full
                    break

            return info

        except Exception as e:
            return {"error": str(e)}

    def fetch_page_assets(self, url: str) -> dict[str, bytes]:
        """Fetch spec/image assets melalui browser asset resolver.

        Capability tambahan; tidak mengubah search() atau fetch_url().
        """
        from agent_reach.agent_browser_asset_resolver import (
            AgentBrowserAssetResolver,
        )

        resolver = AgentBrowserAssetResolver()
        return resolver.fetch_spec_assets(url)

    def fetch_url(self, url: str) -> str:
        """Ambil konten dari URL apapun. Connectors > yt-dlp > Jina > Browser."""
        try:
            logger.info(f"[fetch] url={url}")

            from agent_reach.connectors.discourse import DiscourseConnector
            dc = DiscourseConnector()
            if dc.detect(url):
                logger.info("[fetch] connector=discourse")
                doc = dc.fetch(url)
                if doc and doc.platform == "discourse":
                    return self._format_discourse(doc)

            if any(d in url for d in ["youtube.com", "youtu.be", "tiktok.com", "instagram.com/reel"]):
                logger.info("[fetch] connector=yt-dlp")
                result = subprocess.run(
                    ["yt-dlp", "--dump-json", "--skip-download", url],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    return f"""
Judul: {data.get('title','')}
Uploader: {data.get('uploader','')}
Durasi: {data.get('duration',0)} detik
Deskripsi: {data.get('description','')[:1000]}
URL: {url}
"""

            if "github.com" in url:
                api_url = url.replace("github.com", "api.github.com/repos").replace("/blob/", "/contents/")
                result = subprocess.run(
                    [
                        "curl", "-sS", "-L",
                        "-H", "Accept: application/vnd.github+json",
                        "-w", "\n__FETCH_HTTP_STATUS__:%{http_code}\n",
                        api_url,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                github_body, github_status = split_http_status(
                    result.stdout or ""
                )
                github_ok, github_reason = validate_github_response(
                    github_body,
                    github_status,
                )
                if github_ok:
                    return github_body[:2000]
                return f"Error GitHub: {github_reason}"

            result = subprocess.run(
                [
                    "curl", "-sS", "-L",
                    "-w", "\n__FETCH_HTTP_STATUS__:%{http_code}\n",
                    f"https://r.jina.ai/{url}",
                ],
                capture_output=True, text=True, timeout=15
            )
            jina_body, jina_status = split_http_status(result.stdout or "")
            jina_class = classify_fetch_result(jina_body, jina_status)

            if jina_class == FetchClass.SUCCESS:
                return jina_body[:8000]

            browser_classes = {
                FetchClass.BLOCK,
                FetchClass.JS_REQUIRED,
                FetchClass.BROWSER_REQUIRED,
            }
            if jina_class not in browser_classes:
                return f"Error fetch: {jina_class.value}"

            logger.info(
                "[fetch] browser_fallback url=%s reason=%s",
                url,
                jina_class.value,
            )
            from agent_reach.browser_tool import BrowserTool
            bt = BrowserTool()
            profile = "github" if "github.com" in url else "default"
            browser_result = bt.fetch(url, profile=profile)
            browser_class = classify_fetch_result(browser_result)

            if browser_class == FetchClass.SUCCESS:
                return browser_result

            return f"Error fetch: browser_{browser_class.value}"

        except Exception as e:
            return f"Error fetch: {e}"

    def search(
        self,
        query: str,
        sources: list = None,
        allow_video: bool = False,
        allow_social: bool = False,
    ) -> str:
        if sources is None:
            sources = ["searxng"]

        results = []

        for src in sources:
            if src == "searxng":
                exa_out = None
                try:
                    import asyncio
                    from agent_reach.discovery_exa import ExaDiscoveryTool

                    discovery = ExaDiscoveryTool()
                    exa_raw = self._run_async_sync(
                        discovery.search(query, num_results=5)
                    )

                    if exa_raw:
                        self._active_query = query
                        normalized = [
                            {
                                "title": item.title,
                                "url": item.url,
                                "content": item.highlights,
                                "engine": "exa",
                                "score": 0.0,
                                "category": "general",
                            }
                            for item in exa_raw
                        ]

                        ranked = self._score_and_rank(
                            normalized, 5, "general,it"
                        )

                        if self._has_sufficient_upstream_results(ranked):
                            lines = []
                            for score, item in ranked[:5]:
                                title = item.get("title", "")
                                url = item.get("url", "")
                                snippet = item.get("content", "")[:150]
                                engine = item.get("engine", "exa")
                                lines.append(
                                    f"- [{engine}] {title}\n"
                                    f"  {snippet}\n"
                                    f"  {url}\n"
                                )

                            if lines:
                                exa_out = "".join(lines)

                except Exception as exc:
                    logger.warning(
                        "[search] Exa primary lookup failed, falling back: %s",
                        exc,
                    )
                    exa_out = None

                if exa_out:
                    results.append(f"[EXA]\n{exa_out}")
                else:
                    r = self.search_searxng(
                        query,
                        allow_video=allow_video,
                        allow_social=allow_social,
                    )
                    if r:
                        results.append(f"[{src.upper()}]\n{r}")

        return "\n\n".join(results) if results else "Tidak ada hasil pencarian."

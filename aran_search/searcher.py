import subprocess
import json
import urllib.parse
from urllib.parse import urlparse
import logging
import asyncio
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
        "searxng",
    ]

    # Aran Reach search upstreams.
    UPSTREAMS = (
        ("google cse", 10),
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
            results = data.get("results", [])[:limit]

            logger.info(
                "[AUDIT RAW ENGINE RESULTS] engine=%s query=%r count=%d results=%s",
                engine,
                query,
                len(results),
                [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "content": r.get("content", "")[:200],
                    }
                    for r in results
                ],
            )

            return results

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

        # PATCH (url-entity-scoring): entity-path tokens = capitalized
        # mid-sentence tokens from the RAW query (proper-noun-like),
        # excluding the sentence-initial token to avoid false positives
        # (e.g. "What"). Used only for path_bonus below; generic
        # descriptive words never qualify.
        raw_tokens_all = re.findall(
            r"[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)+|[a-zA-Z0-9]+",
            raw_query,
        )
        path_entity_tokens = [
            tok.lower()
            for i, tok in enumerate(raw_tokens_all)
            if i > 0
            and tok[:1].isupper()
            and tok.lower() in query_tokens
        ]

        scored = []

        for r in results:
            url = r.get("url", "")
            netloc = urlparse(url).netloc.lower()

            if any(d in netloc for d in self.BLOCKED):
                continue

            title = r.get("title", "")
            content = r.get("content", "")
            # PATCH (url-entity-scoring): URL now included so entity
            # mentions that only exist in the URL (not title/content)
            # count toward matches AND can satisfy the anchor-token gate
            # below.
            haystack = f"{title} {content} {url}".lower()

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
                if engine in ["google cse", "brave"]
                else 0.0
            )

            # PATCH (url-entity-scoring): deterministic path-specific
            # bonus. Restricted to path_entity_tokens only (proper-noun-
            # like, never generic descriptive words such as
            # current/updated/last/price), applied only against the URL
            # PATH; rewards canonical entity pages over generic pages
            # sharing the same domain. Implemented independently of
            # token_present (which is bound to `haystack`) so that
            # function's signature is left unchanged.
            path_text = urlparse(url).path.lower()
            path_bonus = 3.0 * sum(
                bool(re.search(
                    rf"(?<![a-zA-Z0-9]){re.escape(tok)}(?![a-zA-Z0-9])",
                    path_text,
                ))
                for tok in path_entity_tokens
            )

            score = (
                base_score
                + relevance_bonus
                + entity_bonus
                + official_bonus
                + domain_bonus
                + engine_bonus
                + path_bonus
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

    def _format_weather(self, doc) -> str:
        if not doc or not doc.metadata:
            return "Error Weather: Dokumen kosong"
        meta = doc.metadata
        if meta.get("error"):
            return (
                f"Error Weather: {meta.get('error')}\n"
                f"Location: {meta.get('location', '')}\n"
                f"Source: {doc.source_url}\n"
            )

        temp_unit = "C"
        precip_unit = meta.get("precipitation_unit") or "mm"
        humidity_unit = meta.get("humidity_unit") or "%"
        wind_unit = meta.get("wind_speed_unit") or "km/h"

        lines = [
            "[WEATHER OFFICIAL API - OPEN-METEO]",
            f"Location: {meta.get('location', '')}, {meta.get('country', '')}",
        ]
        if meta.get("admin1"):
            lines.append(f"Region/Admin: {meta.get('admin1')}")
        lines.extend([
            f"Coordinates: Lat {meta.get('latitude')}, Lon {meta.get('longitude')}",
            f"Timezone: {meta.get('timezone', 'UTC')}",
            f"Current Timestamp: {meta.get('current_timestamp', '')}",
            f"Current Temperature: {meta.get('current_temperature')} {temp_unit}",
            f"Current Condition: {meta.get('current_weather_desc', '')} (Code: {meta.get('current_weather_code', '')})",
            f"Current Humidity: {meta.get('current_humidity')} {humidity_unit}",
            f"Current Precipitation: {meta.get('current_precipitation')} {precip_unit}",
            f"Current Rain: {meta.get('current_rain')} {precip_unit}",
            f"Current Wind Speed: {meta.get('current_wind_speed')} {wind_unit}",
        ])

        target_forecast = meta.get("target_date_forecast")
        if target_forecast:
            lines.extend([
                "",
                "[TARGET DATE FORECAST]",
                f"Target Date: {target_forecast.get('date')}",
                f"Highest Temperature (temperature_2m_max): {target_forecast.get('temperature_2m_max')} {temp_unit}",
                f"Lowest Temperature (temperature_2m_min): {target_forecast.get('temperature_2m_min')} {temp_unit}",
                f"Expected Precipitation: {target_forecast.get('precipitation_sum')} {precip_unit}",
                f"Expected Rain: {target_forecast.get('rain_sum')} {precip_unit}",
            ])
        elif meta.get("target_date"):
            lines.extend([
                "",
                f"[TARGET DATE FORECAST: {meta.get('target_date')} - Note: Target date outside standard 7-day daily forecast window]",
            ])

        daily_list = meta.get("forecast_daily", [])
        if daily_list:
            lines.extend(["", "[DAILY FORECAST SUMMARY]"])
            for day in daily_list:
                lines.append(
                    f"- Date {day.get('date')}: Max {day.get('temperature_2m_max')} {temp_unit}, "
                    f"Min {day.get('temperature_2m_min')} {temp_unit}, "
                    f"Precip {day.get('precipitation_sum')} {precip_unit}, "
                    f"Rain {day.get('rain_sum')} {precip_unit}"
                )

        lines.extend([
            "",
            f"API Provider: Open-Meteo Weather API ({meta.get('api_url', 'https://api.open-meteo.com')})",
            f"Source: {doc.source_url}",
        ])
        return "\n".join(lines)

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
        from aran_search.agent_browser_asset_resolver import (
            AgentBrowserAssetResolver,
        )

        resolver = AgentBrowserAssetResolver()
        return resolver.fetch_spec_assets(url)

    def _is_valid_binance_symbol(self, symbol: str) -> bool:
        """Validasi read-only ke Binance exchangeInfo apakah symbol aktif TRADING."""
        if not hasattr(self, "_binance_symbol_cache"):
            self._binance_symbol_cache = {}

        if symbol in self._binance_symbol_cache:
            return self._binance_symbol_cache[symbol]

        try:
            try:
                import httpx
                resp = httpx.get(
                    "https://api.binance.com/api/v3/exchangeInfo",
                    params={"symbol": symbol},
                    timeout=5,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    symbols = data.get("symbols", [])
                    if symbols and symbols[0].get("status") == "TRADING":
                        self._binance_symbol_cache[symbol] = True
                        return True
            except ImportError:
                import json
                import urllib.request
                req = urllib.request.Request(
                    f"https://api.binance.com/api/v3/exchangeInfo?symbol={symbol}",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode())
                    symbols = data.get("symbols", [])
                    if symbols and symbols[0].get("status") == "TRADING":
                        self._binance_symbol_cache[symbol] = True
                        return True
        except Exception:
            pass

        self._binance_symbol_cache[symbol] = False
        return False

    def _canonicalize_binance_url(self, url: str) -> str:
        """Mengubah URL SEO /price/<slug> Binance menjadi canonical /trade/<BASE>_<QUOTE>."""
        import re
        match = re.search(
            r"^https?://(?:www\.)?binance\.com/(?:[a-z]{2}/)?price/([a-z0-9_-]+)/?$",
            url,
            re.IGNORECASE,
        )
        if not match:
            return url

        slug = match.group(1).lower()

        if slug in {
            "all", "hot-coins", "market", "markets",
            "overview", "archive", "ranking",
        }:
            return url

        base = None
        quote = "USDT"

        pair_match = re.match(
            r"^([a-z0-9]+)[-_]?(usdt|usdc|fdusd|btc)$",
            slug,
        )

        if pair_match:
            base = pair_match.group(1).upper()
            quote = pair_match.group(2).upper()
        else:
            KNOWN_SLUG_MAP = {
                "bitcoin": "BTC",
                "ethereum": "ETH",
                "solana": "SOL",
                "ripple": "XRP",
                "dogecoin": "DOGE",
                "cardano": "ADA",
                "binance-coin": "BNB",
                "polkadot": "DOT",
                "avalanche": "AVAX",
                "chainlink": "LINK",
            }

            if slug in KNOWN_SLUG_MAP:
                base = KNOWN_SLUG_MAP[slug]

        if not base or base == quote:
            return url

        candidate_symbol = f"{base}{quote}"

        if self._is_valid_binance_symbol(candidate_symbol):
            return f"https://www.binance.com/en/trade/{base}_{quote}"

        return url

    def fetch_url(self, url: str) -> str:
        """Ambil konten dari URL apapun. Connectors > yt-dlp > Jina > Browser."""
        try:
            logger.info(f"[fetch] url={url}")

            from aran_search.connectors.discourse import DiscourseConnector
            from aran_search.connectors.coingecko import CoinGeckoConnector
            from aran_search.connectors.binance_futures import BinanceFuturesConnector
            from aran_search.connectors.binance import BinanceConnector
            from aran_search.connectors.polymarket import PolymarketConnector
            from aran_search.connectors.weather import WeatherConnector

            dc = DiscourseConnector()
            if dc.detect(url):
                logger.info("[fetch] connector=discourse")
                doc = dc.fetch(url)
                if doc and doc.platform == "discourse":
                    return self._format_discourse(doc)

            cg = CoinGeckoConnector()
            if cg.detect(url):
                logger.info("[fetch] connector=coingecko")
                doc = cg.fetch(url)
                if doc and doc.platform == "coingecko":
                    if doc.metadata.get("error"):
                        logger.warning(
                            "[fetch] connector=coingecko failed coin_id=%s error=%s",
                            doc.metadata.get("coin_id"),
                            doc.metadata.get("error"),
                        )
                        return (
                            "Error CoinGecko: "
                            f"{doc.metadata.get('error')}"
                        )
                    else:
                        return (
                            "[COINGECKO OFFICIAL API]\n"
                            f"Coin: {doc.metadata.get('coin_id', '')}\n"
                            f"Price: ${doc.metadata.get('price_usd', '')} USD\n"
                            f"Last updated: {doc.metadata.get('last_updated_utc', '')}\n"
                            f"Source: {doc.source_url}\n"
                        )

            bf = BinanceFuturesConnector()
            if bf.detect(url):
                logger.info(
                    "[fetch] connector=binance-futures url=%s",
                    url,
                )
                doc = bf.fetch(url)
                if doc and doc.platform == "binance-futures":
                    if doc.metadata.get("error"):
                        logger.warning(
                            "[fetch] connector=binance-futures failed symbol=%s error=%s",
                            doc.metadata.get("symbol"),
                            doc.metadata.get("error"),
                        )
                        return (
                            "Error Binance Futures: "
                            f"{doc.metadata.get('error')}"
                        )
                    return (
                        "[BINANCE FUTURES OFFICIAL API]\n"
                        f"Symbol: {doc.metadata.get('symbol', '')}\n"
                        f"Last price: {doc.metadata.get('last_price', '')}\n"
                        f"24h change: {doc.metadata.get('price_change', '')} "
                        f"({doc.metadata.get('price_change_percent', '')}%)\n"
                        f"24h high: {doc.metadata.get('high_price', '')}\n"
                        f"24h low: {doc.metadata.get('low_price', '')}\n"
                        f"Volume: {doc.metadata.get('volume', '')}\n"
                        f"Quote volume: {doc.metadata.get('quote_volume', '')}\n"
                        f"Mark price: {doc.metadata.get('mark_price', '')}\n"
                        f"Index price: {doc.metadata.get('index_price', '')}\n"
                        f"Funding rate: {doc.metadata.get('last_funding_rate_percent', '')} "
                        f"({doc.metadata.get('last_funding_rate', '')})\n"
                        f"Next funding time: {doc.metadata.get('next_funding_time_utc', '')}\n"
                        f"Close time: {doc.metadata.get('close_time_utc', '')}\n"
                        f"Source: {doc.source_url}\n"
                    )

            target_url = self._canonicalize_binance_url(url)
            bn = BinanceConnector()
            if bn.detect(target_url):
                logger.info(
                    "[fetch] connector=binance url=%s",
                    target_url,
                )
                doc = bn.fetch(target_url)
                if doc and doc.platform == "binance":
                    if doc.metadata.get("error"):
                        logger.warning(
                            "[fetch] connector=binance failed symbol=%s error=%s",
                            doc.metadata.get("symbol"),
                            doc.metadata.get("error"),
                        )
                        return (
                            "Error Binance: "
                            f"{doc.metadata.get('error')}"
                        )
                    return (
                        "[BINANCE OFFICIAL API]\n"
                        f"Symbol: {doc.metadata.get('symbol', '')}\n"
                        f"Last price: {doc.metadata.get('last_price', '')}\n"
                        f"24h change: {doc.metadata.get('price_change', '')} "
                        f"({doc.metadata.get('price_change_percent', '')}%)\n"
                        f"24h high: {doc.metadata.get('high_price', '')}\n"
                        f"24h low: {doc.metadata.get('low_price', '')}\n"
                        f"Volume: {doc.metadata.get('volume', '')}\n"
                        f"Quote volume: {doc.metadata.get('quote_volume', '')}\n"
                        f"Close time: {doc.metadata.get('close_time_utc', '')}\n"
                        f"Source: {doc.source_url}\n"
                    )

            pm = PolymarketConnector()
            if pm.detect(url):
                logger.info(
                    "[fetch] connector=polymarket url=%s",
                    url,
                )
                doc = pm.fetch(url)
                if doc and doc.platform == "polymarket":
                    if doc.metadata.get("error"):
                        logger.warning(
                            "[fetch] connector=polymarket failed slug=%s error=%s",
                            doc.metadata.get("slug"),
                            doc.metadata.get("error"),
                        )
                        return (
                            "Error Polymarket: "
                            f"{doc.metadata.get('error')}"
                        )

                    out = (
                        "[POLYMARKET OFFICIAL API]\n"
                        f"Event: {doc.metadata.get('title', '')}\n"
                        f"Description: {doc.metadata.get('description', '')}\n"
                        f"Resolution source: "
                        f"{doc.metadata.get('resolution_source', '')}\n"
                        f"Volume: {doc.metadata.get('volume', '')}\n"
                        f"Liquidity: {doc.metadata.get('liquidity', '')}\n"
                        f"Active: {doc.metadata.get('active', '')}\n"
                        f"Closed: {doc.metadata.get('closed', '')}\n"
                    )

                    for market in doc.metadata.get("markets", []):
                        out += (
                            f"Market: {market.get('question', '')}\n"
                            f"Outcomes: {market.get('outcomes', '')}\n"
                            f"Outcome prices: "
                            f"{market.get('outcome_prices', '')}\n"
                            f"Best bid: {market.get('best_bid', '')}\n"
                            f"Best ask: {market.get('best_ask', '')}\n"
                            f"Spread: {market.get('spread', '')}\n"
                            f"Last trade price: "
                            f"{market.get('last_trade_price', '')}\n"
                            f"Volume: {market.get('volume', '')}\n"
                            f"Liquidity: {market.get('liquidity', '')}\n"
                        )

                    out += f"Source: {doc.source_url}\n"
                    return out

            wc = WeatherConnector()
            if wc.detect(url):
                logger.info(
                    "[fetch] connector=weather url=%s",
                    url,
                )
                doc = wc.fetch(url)
                if doc and doc.platform == "weather":
                    return self._format_weather(doc)

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
                result = subprocess.run(["curl", "-s", api_url], capture_output=True, text=True, timeout=10)
                if result.stdout:
                    return result.stdout[:2000]

            host = urlparse(url).netloc.lower().split(":")[0]

            if host == "coinmarketcap.com" or host.endswith(".coinmarketcap.com") or host == "coingecko.com" or host.endswith(".coingecko.com"):
                logger.info(
                    "[fetch] browser_first url=%s host=%s reason=js_heavy_domain",
                    url,
                    host,
                )
                from aran_search.browser_tool import BrowserTool
                bt = BrowserTool()
                browser_result = bt.fetch(url)

                if browser_result and not browser_result.startswith("Error:"):
                    return browser_result

                logger.warning(
                    "[fetch] browser_first_failed url=%s; falling back to jina",
                    url,
                )

            result = subprocess.run(
                ["curl", "-s", "-L", f"https://r.jina.ai/{url}"],
                capture_output=True, text=True, timeout=15
            )
            if result.stdout and len(result.stdout) > 800:
                return result.stdout[:8000]

            logger.info(
                "[fetch] jina_insufficient url=%s chars=%d; trying browser",
                url,
                len(result.stdout or ""),
            )
            from aran_search.browser_tool import BrowserTool
            bt = BrowserTool()
            browser_result = bt.fetch(url)

            if browser_result:
                return browser_result

            return result.stdout or "Tidak ada konten yang berhasil diambil."

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
                            normalized,
                            5,
                            "general,it",
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

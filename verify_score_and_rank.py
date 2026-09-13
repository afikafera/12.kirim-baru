# -*- coding: ascii -*-
import re
import logging
from urllib.parse import urlparse

from aran_search.searcher import AgentReachSearcher

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("aran_search.searcher")

QUERY = (
    "What is the current Bitcoin price according to CoinGecko, "
    "and when was the price last updated?"
)

# ---------------------------------------------------------------------
# Production fixture, captured verbatim via capture_exa_fixture.py
# ---------------------------------------------------------------------
FIXTURE = [
    {
        "title": "Bitcoin Price Chart (BTC)",
        "url": "https://www.coingecko.com/en/coins/bitcoin",
        "content": "BTC Price\n#1\n$62,814.45\n0.3%\n1.0000 BTC 0.0%\n$62,460.60 24h Range $64,155.54\nWhy BTC is moving\nBitcoin Rebounds as Strategy Buys 1,550 BTC Amid Market Recovery\n4 sources\n7 hours ago\n## BTC Historical Price\n| 24h Range | $62,460.60 - $64,155.54 |\n| --- | --- |\n| 7d Range | $59,353.42 - $70,843.71 |\n| All-Time High | $126,080 50.2% Oct 06, 2025 (8 months) |\n| All-Time Low | $67.81 92534.4% Jul 06, 2013 (almost 13 years) |\n### Trending Coins\n## Bitcoin (BTC) price has declined today.\nThe price of Bitcoin (BTC) is $62,814.45 today with a 24-hour trading volume of $34,409,633,517.57. This represents a -0.30% price decline in the last 24 hours and a -11.10% price decline in the past 7 days. With a circulating supply of 20 Million BTC, Bitcoin is valued at a market cap of $1,259,216,323,962.\nBitcoin Rebounds as Strategy Buys 1,550 BTC Amid Market Recovery\n4 sources\n7 hours ago\n35 minutes\n39 minutes\nabout 2 hours\nabout 3 hours\nMicroStrategy Acquires 1,550 BTC After Prior Sale\nFutures Capitulation Drove Bitcoin's 16% Selloff\n+16 chains\n+16 chains\nLooks like\nadded some coins before logging in. Merge them with\nsaved portfolio to keep everything in one place.\nYou will receive an email with instructions for how to confirm your email address in a few minutes.\n+16 chains\nWe only fetch public data. No private keys, no signing, and we can't make any changes to your wallet.\n? ? ? ? ? ? ? ? ? ? ? ?\nMaybe Later\nRemove Coins\nYou've reached the limit.",
        "engine": "exa",
        "score": 0.0,
        "category": "general",
    },
    {
        "title": "FAQ | CoinGecko",
        "url": "https://www.coingecko.com/en/faq",
        "content": "Coin Price refers to the current global volume-weighted average price of a cryptoasset traded on an active cryptoasset exchange as tracked by CoinGecko. Market Capitalization is one of the metrics used to measure the relative size of a cryptoasset. Market Capitalization is calculated by multiplying Coin Price with Circulating Supply. Volume is the total trading volume of a cryptoasset across all active cryptoasset exchanges tracked by CoinGecko. Trust Score is used to measure liquidity on trading pairs and crypto exchanges. It is also expanded to measure overall liquidity, scale of operations and API coverage. For a detailed explanation, read more about it on our Methodology page.\n1. Our bots update our data based on a variable schedule. We update our information whenever possible as scheduled below, subject to rate-limits imposed by data providers.\n2. 1. Price, trading volume, market capitalization - Updated every 1 to 10 minutes\n2. Circulating supply - Updated every 5 minutes\n3. Developer, Social and Alexa Data - updated once per day\n4. Blockchain information (Mining difficulty, total blocks, transactions per second etc.) - updated every 1 hour",
        "engine": "exa",
        "score": 0.0,
        "category": "general",
    },
    {
        "title": "CoinGecko: Cryptocurrency Prices, Charts, and Crypto Market ...",
        "url": "https://www.coingecko.com/",
        "content": "| # | Coin | | Price | 1h | 24h | 7d | 30d | 24h Volume | Market Cap | FDV | Market Cap / FDV | Last 7 Days |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n| 1 | Bitcoin BTC | Buy | $64,592.10 | 0.4% | 0.9% | 0.6% | 2.5% | $22,252,972,412 | $1,296,140,169,978 | $1,296,142,947,451 | 1.0 | |",
        "engine": "exa",
        "score": 0.0,
        "category": "general",
    },
    {
        "title": "BTC USD - Bitcoin Price and Chart",
        "url": "https://www.tradingview.com/symbols/BTCUSD/",
        "content": "The current price of Bitcoin (BTC) is 64,026 USD - it has risen 0.94% in the past 24 hours. Try placing this info into the context by checking out what coins are also gaining and losing at the moment and seeing BTC price chart.",
        "engine": "exa",
        "score": 0.0,
        "category": "general",
    },
    {
        "title": "Bitcoin (BTC) Price Today: BTC Live Price, Charts, News",
        "url": "https://crypto.com/us/price/bitcoin",
        "content": "| Time | Price | Change |\n| --- | --- | --- |\n| Today | $80,891.13 | 0.00% |\n| 1 day | $77,477.01 | +$3,414.12 (4.45%) |\n| 1 week | $80,900.53 | -$9.40 (0.10%) |\n| 1 month | $64,284.28 | +$16,606.85 (26.00%) |\n| 1 year | $110,825.22 | -$29,934.09 (26.67%) |\nBitcoin's price today is $80,891.13, with a 24-hour trading volume of $41.1B. BTC is +4.45% in the last 24 hours. It is currently -1.48% from its 7-day all-time high of $82,103.23, and 6.06% from its 7-day all-time low of $76,272.24.BTC has a circulating supply of 20.08M BTC and a max supply of 21M BTC.\n$80,891.13",
        "engine": "exa",
        "score": 0.0,
        "category": "general",
    },
]


def run_baseline(fixture):
    print("=" * 90)
    print("STEP 1 - BASELINE (real, unmodified aran_search.searcher.AgentReachSearcher)")
    print("=" * 90)
    s = AgentReachSearcher()
    s._active_query = QUERY
    ranked = s._score_and_rank(list(fixture), 5, "general,it")

    print("\n--- Final returned list (post-filter, post-dedup, order = final rank) ---")
    for i, (score, r) in enumerate(ranked, 1):
        print(f"{i}. score={score:.2f} url={r['url']}")

    survivors = {r["url"] for _, r in ranked}
    dropped = [f["url"] for f in fixture if f["url"] not in survivors]
    print("\n--- URLs from fixture NOT present in final output (dropped by gate OR lost to dedup) ---")
    for u in dropped:
        print(f"  DROPPED: {u}")

    bitcoin_url = "https://www.coingecko.com/en/coins/bitcoin"
    faq_url = "https://www.coingecko.com/en/faq"
    bitcoin_survived = bitcoin_url in survivors
    faq_survived = faq_url in survivors
    print(f"\nBitcoin canonical page survived to final output: {bitcoin_survived}")
    print(f"FAQ page survived to final output: {faq_survived}")

    coingecko_representative = None
    for score, r in ranked:
        if urlparse(r["url"]).netloc.lower().endswith("coingecko.com"):
            coingecko_representative = r["url"]
            break
    print(f"CoinGecko representative after dedup: {coingecko_representative}")

    return ranked, bitcoin_survived, faq_survived, coingecko_representative


# ---------------------------------------------------------------------
# STEP 2 - candidate patch, defined as a subclass override.
# Body is the REAL method (verbatim) with minimal diff, marked "# PATCH:".
# Production file aran_search/searcher.py is NEVER modified.
# ---------------------------------------------------------------------
class CandidateSearcher(AgentReachSearcher):

    def _score_and_rank(self, results: list, max_output: int, category_label: str = "") -> list:
        raw_query = getattr(self, "_active_query", "")
        query = raw_query.lower()

        stopwords = {
            "dan", "di", "ke", "dari", "untuk", "dengan", "yang",
            "ini", "itu", "the", "a", "an", "of", "in", "on", "at",
            "to", "for", "with", "by", "from", "and",
            "spesifikasi", "specification", "specifications",
            "review", "harga", "price", "beli", "buy",
        }

        query_tokens = [
            token.lower()
            for token in re.findall(
                r"[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)+|[a-zA-Z0-9]+",
                query,
            )
            if len(token) > 1 and token not in stopwords
        ]

        # PATCH: entity-path candidate tokens = capitalized mid-sentence
        # tokens from the RAW (non-lowered) query, excluding the
        # sentence-initial token (index 0) to avoid false positives like
        # "What". This deliberately excludes generic lowercase
        # descriptive words (current/updated/last/was/when/according),
        # satisfying "generic URL tokens must not get a bonus".
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
            # PATCH: URL now included in haystack, so entity mentions
            # that only appear in the URL (not in title/content) count
            # toward matches AND satisfy the anchor-token gate below.
            haystack = f"{title} {content} {url}".lower()

            def token_present(token: str, text: str = haystack) -> bool:
                return bool(
                    re.search(
                        rf"(?<![a-zA-Z0-9]){re.escape(token)}(?![a-zA-Z0-9])",
                        text,
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
                "[CANDIDATE AUDIT SEARCH GATE] category=%s url=%s matches=%d matched=%s entity_match=%s",
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

            # PATCH: deterministic path-specific bonus. Restricted to
            # path_entity_tokens only (proper-noun-like, not generic
            # descriptive words), applied only against the URL PATH
            # (not netloc, not title/content) so it specifically
            # rewards canonical entity pages over generic pages that
            # merely share the same domain.
            path_text = urlparse(url).path.lower()
            path_bonus = 3.0 * sum(
                token_present(tok, path_text) for tok in path_entity_tokens
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


def run_candidate(fixture, label="STEP 2 - CANDIDATE"):
    print("\n" + "=" * 90)
    print(label)
    print("=" * 90)
    s = CandidateSearcher()
    s._active_query = QUERY
    ranked = s._score_and_rank(list(fixture), 5, "general,it")

    print("\n--- Final returned list (order = final rank) ---")
    for i, (score, r) in enumerate(ranked, 1):
        print(f"{i}. score={score:.2f} url={r['url']}")

    coingecko_representative = None
    for score, r in ranked:
        if urlparse(r["url"]).netloc.lower().endswith("coingecko.com"):
            coingecko_representative = r["url"]
            break
    print(f"CoinGecko representative after dedup: {coingecko_representative}")
    return ranked, coingecko_representative


if __name__ == "__main__":
    baseline_ranked, bitcoin_survived, faq_survived, baseline_rep = run_baseline(FIXTURE)
    candidate_ranked, candidate_rep = run_candidate(FIXTURE)

    print("\n" + "=" * 90)
    print("STEP 4 - COMPARE (production fixture)")
    print("=" * 90)
    print(f"{'metric':35s} {'baseline':35s} {'candidate'}")
    print(f"{'CoinGecko representative':35s} {str(baseline_rep):35s} {str(candidate_rep)}")

    bitcoin_url = "https://www.coingecko.com/en/coins/bitcoin"
    print(f"\nBitcoin canonical page selected as CoinGecko representative:")
    print(f"  baseline : {baseline_rep == bitcoin_url}")
    print(f"  candidate: {candidate_rep == bitcoin_url}")

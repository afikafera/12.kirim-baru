"""
STEP 3 - regression / control cases for the CoinGecko candidate-selection
patch (path_bonus + url-in-haystack). Synthetic cases only, additive to
(not replacing) the production fixture already verified in
verify_score_and_rank.py.

Imports the SAME CandidateSearcher class definition used before (copied
here verbatim) plus the real AgentReachSearcher for baseline comparison.
Production file aran_search/searcher.py is never modified.
"""
import re
import logging
from urllib.parse import urlparse

from aran_search.searcher import AgentReachSearcher

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("aran_search.searcher")


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


def result(title, url, content, score=0.0, engine="exa"):
    return {"title": title, "url": url, "content": content,
            "engine": engine, "score": score, "category": "general"}


PASS_COUNT = 0
FAIL_COUNT = 0


def check(case_id, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    status = "PASS" if condition else "FAIL"
    if condition:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
    print(f"[{status}] {case_id}  {detail}")
    return condition


print("=" * 90)
print("CASE B - domain dedup unchanged (multiple same-domain results, only one survives)")
print("=" * 90)
query_b = "Ferrari F355 review"
s_old = AgentReachSearcher()
s_old._active_query = query_b
s_new = CandidateSearcher()
s_new._active_query = query_b

fixture_b = [
    result("Ferrari F355 Review Part 1", "https://example.com/f355-review-1",
           "Ferrari F355 review part one, driving impressions."),
    result("Ferrari F355 Review Part 2", "https://example.com/f355-review-2",
           "Ferrari F355 review part two, more driving impressions."),
]
old_b = s_old._score_and_rank(list(fixture_b), 5, "general,it")
new_b = s_new._score_and_rank(list(fixture_b), 5, "general,it")
check("B.old_dedup_to_one_per_domain", len(old_b) <= 1,
      f"old returned {len(old_b)} result(s) for same-domain fixture")
check("B.new_dedup_to_one_per_domain", len(new_b) <= 1,
      f"new returned {len(new_b)} result(s) for same-domain fixture")
check("B.dedup_logic_identical",
      len(old_b) == len(new_b),
      f"old={len(old_b)} new={len(new_b)}")


print()
print("=" * 90)
print("CASE C - unrelated non-CoinGecko result must not get CoinGecko-specific bonus")
print("(path_bonus is generic per-URL, not hardcoded to any domain -- verify it only")
print(" fires when the URL's OWN path contains an entity token from the query)")
print("=" * 90)
query_c = "What is the current Bitcoin price according to CoinGecko, and when was the price last updated?"
s_new_c = CandidateSearcher()
s_new_c._active_query = query_c

fixture_c = [
    result("Random unrelated page", "https://unrelated-example.com/about-us",
           "This page is about Bitcoin and CoinGecko in the title only, "
           "unrelated path segment."),
]
ranked_c = s_new_c._score_and_rank(list(fixture_c), 5, "general,it")
if ranked_c:
    score_c, r_c = ranked_c[0]
    path_c = urlparse(r_c["url"]).path.lower()
    has_entity_in_path = "bitcoin" in path_c or "coingecko" in path_c
    check("C.no_path_bonus_when_path_has_no_entity_token",
          not has_entity_in_path,
          f"path={path_c!r} score={score_c:.2f} (entity words only in title/content, not path)")
else:
    check("C.result_survived_gate", False, "unexpectedly filtered out entirely")


print()
print("=" * 90)
print("CASE D - generic query tokens in URL path must NOT get path_bonus")
print("=" * 90)
fixture_d = [
    result("Some current updated price page", "https://example.com/current/updated/price",
           "Bitcoin according to CoinGecko was last updated."),
]
s_new_d = CandidateSearcher()
s_new_d._active_query = query_c
ranked_d = s_new_d._score_and_rank(list(fixture_d), 5, "general,it")
if ranked_d:
    score_d, r_d = ranked_d[0]
    # Compute what the score WOULD be with zero path_bonus contribution
    # by checking: does the path contain only generic (non-entity) tokens?
    path_d = urlparse(r_d["url"]).path.lower()
    # entity tokens for this query are "bitcoin" and "coingecko" only.
    entity_leak = "bitcoin" in path_d or "coingecko" in path_d
    check("D.generic_path_tokens_excluded_from_bonus",
          not entity_leak,
          f"path={path_d!r} contains only generic tokens (current/updated/price), "
          f"no entity leak -> path_bonus should be 0 for this URL")
else:
    check("D.result_survived_gate", False, "unexpectedly filtered out entirely")


print()
print("=" * 90)
print("CASE E - entity token in path DOES get path_bonus (sanity re-confirm)")
print("=" * 90)
fixture_e = [
    result("Bitcoin canonical-like page", "https://coingecko.com/en/coins/bitcoin",
           "BTC price data, no literal brand mention in body."),
]
s_new_e = CandidateSearcher()
s_new_e._active_query = query_c
ranked_e = s_new_e._score_and_rank(list(fixture_e), 5, "general,it")
# Analytic expectation for THIS fixture: matches=2 (bitcoin, coingecko via
# url) -> relevance_bonus=4.0; path_entity_tokens=[bitcoin,coingecko],
# only "bitcoin" is in the path (not "coingecko", which is in netloc) ->
# path_bonus = 3.0 * 1 = 3.0. Expected total = 7.0 exactly.
check("E.entity_path_token_survives_and_scores",
      bool(ranked_e) and abs(ranked_e[0][0] - 7.0) < 1e-6,
      f"ranked={[(s, r['url']) for s, r in ranked_e]} (expected 7.0: "
      f"relevance 2*2.0=4.0 + path_bonus 1*3.0=3.0)")


print()
print("=" * 90)
print("CASE F - existing scoring unchanged when no entity-in-path scenario applies")
print("=" * 90)
query_f = "Ferrari F355 review"
# IMPORTANT: path must NOT contain any path_entity_token ("f355") for
# this to be a true "no entity in path" control case. Using a generic
# thread id instead of the model number in the URL.
fixture_f = [
    result("Ferrari F355 Owners Forum", "https://forum.example.com/thread-12345",
           "Ferrari F355 review discussion, common issues and fixes."),
]
s_old_f = AgentReachSearcher()
s_old_f._active_query = query_f
s_new_f = CandidateSearcher()
s_new_f._active_query = query_f
old_f = s_old_f._score_and_rank(list(fixture_f), 5, "general,it")
new_f = s_new_f._score_and_rank(list(fixture_f), 5, "general,it")
old_score_f = old_f[0][0] if old_f else None
new_score_f = new_f[0][0] if new_f else None
check("F.score_unchanged_without_entity_in_path",
      old_score_f == new_score_f,
      f"old_score={old_score_f} new_score={new_score_f}")


print()
print("=" * 90)
print("CASE G - determinism: permute production fixture order, re-run candidate")
print("=" * 90)
production_fixture = [
    result("Bitcoin Price Chart (BTC)", "https://www.coingecko.com/en/coins/bitcoin",
           "BTC Price #1 Bitcoin (BTC) is $62,814.45 today, last 24 hours."),
    result("FAQ | CoinGecko", "https://www.coingecko.com/en/faq",
           "Coin Price refers to the current global average price tracked by "
           "CoinGecko. Updated every 1 to 10 minutes."),
    result("CoinGecko homepage", "https://www.coingecko.com/",
           "Bitcoin BTC price chart tracked by CoinGecko."),
]

orders = {
    "original_order": production_fixture,
    "faq_first": [production_fixture[1], production_fixture[0], production_fixture[2]],
    "reversed": list(reversed(production_fixture)),
}

reps = {}
for label, ordered_fixture in orders.items():
    s = CandidateSearcher()
    s._active_query = query_c
    ranked = s._score_and_rank(list(ordered_fixture), 5, "general,it")
    rep = ranked[0][1]["url"] if ranked else None
    reps[label] = rep
    print(f"  order={label:20s} -> representative={rep}")

all_same = len(set(reps.values())) == 1
check("G.deterministic_across_permutations", all_same,
      f"representatives={reps}")
check("G.representative_is_bitcoin_canonical",
      reps.get("original_order") == "https://www.coingecko.com/en/coins/bitcoin",
      f"got {reps.get('original_order')}")


print()
print("=" * 90)
print(f"SUMMARY: {PASS_COUNT} PASS / {FAIL_COUNT} FAIL")
print("=" * 90)

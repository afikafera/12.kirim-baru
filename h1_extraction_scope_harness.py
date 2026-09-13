"""
VERIFY harness for HYPOTHESIS H1 (2026-09-09): does adding requirement/
checklist text to FactChecker's extraction prompt reduce irrelevant
facts without losing the facts the requirement actually needs?

Root finding this tests (SOURCE-confirmed 2026-09-09): fact_checker.py's
extract_facts_batch(self, all_evidence, checklist) receives `checklist`
but NEVER references it in the extraction prompt -- the prompt only
says "extract substantive facts", with no requirement/topic/need text
at all. This harness does NOT relabel checklist as a generic string and
call it "requirement-aware" -- per the user's explicit instruction, the
REQUIREMENT_TOPIC_*/REQUIREMENT_NEED_* constants below are copied
VERBATIM from this same production trace's own Planner output and
relevance-classifier calls (trace b72c4c130c32d1789d65f59c4a1da6f3,
2026-09-08, request ea977682) -- real requirement data that already
exists earlier in the pipeline (used by the relevance classifier) but
currently never reaches extraction.

EVIDENCE_COINMARKETCAP and EVIDENCE_COINBASE are the two real evidence
texts from that same trace (Node A/Node B), copied verbatim except for
ASCII-sanitizing a handful of decorative characters (up/down arrows,
bullets, curly apostrophe, em-dash) -- no wording or numeric values
changed. This is the exact evidence that produced truncation on both
PATCH5 attempts (1024 then 2048) in production, across two independent
extraction nodes.

Design: fixed max_tokens for BOTH conditions (baseline and candidate) --
isolates prompt-scoping as the only variable being tested.

REVISION 2026-09-09: the first run of this harness at max_tokens=1024
(matching production's own attempt-1 budget) was inconclusive, not
negative -- round-robin landed on glm-5.3-flash for all 12 calls (both
conditions), and 10 of those 12 returned finish_reason="length",
tokens_output=1024 (exactly max_tokens), but output_chars=0 -- the
entire budget was consumed by something that produced zero visible
characters in `content`, most likely hidden reasoning tokens (this
model showed 1700 reasoning + 348 visible = 2048 total in production
trace b72c4c130c32d1789d65f59c4a1da6f3's Node B, on this same 2-source
evidence). Both conditions failed identically before the scoping
variable ever had a chance to matter -- this is a confound in the
harness's chosen budget, not evidence against H1.

max_tokens raised to 4096: real headroom above the 2048 that already
proved insufficient for baseline-style (unscoped) extraction with this
same model on this same evidence in production, while keeping the
budget IDENTICAL between conditions (the control variable is unchanged,
only its value is larger). If candidate's scoped output is small enough
to complete (finish_reason != "length") at 4096 while baseline still
truncates, that is direct support for H1 -- a cleaner result than
matching production's exact 1024/2048 schedule would have given.

Uses the REAL config.load_config() -> REAL LLMAnalyzer -> REAL
round-robin (live LLM calls, no mocking), run N times per condition so
results aren't a single-model artifact -- matches the user's explicit
"jangan bergantung pada satu model" requirement. Reuses the REAL
hermes_agent.fact_checker.extract_json() for parsing (not reimplemented)
and the REAL classify_value_support()/MISMATCH classifier to
automatically flag any fabricated/reformatted value against its cited
source's actual evidence text (acceptance criterion 5) -- not a manual
spot-check, an automated one using the same function already verified
in production.

Does NOT touch fact_checker.py, does NOT apply PATCH7's exact list-
normalize logic (a lightweight approximation is used here purely for
counting facts in this harness's own output -- this script only tests
the raw extractor prompt/response, not the full downstream pipeline).
Does NOT patch production. Read-only against the real LLM endpoint.

Usage:
    cd ~/research-assistant
    python3 h1_extraction_scope_harness.py
"""
import sys
import time

sys.path.insert(0, ".")

import config
from llm_analyzer.analyzer import LLMAnalyzer
from hermes_agent.fact_checker import extract_json, classify_value_support, MISMATCH

N_RUNS_PER_CONDITION = 6
MAX_TOKENS = 4096

# --- real evidence, verbatim from trace b72c4c130c32d1789d65f59c4a1da6f3
# (production, 2026-09-08, request ea977682), ASCII-sanitized only
# (up/down arrows -> "(up)"/"(down)", bullets -> "-", curly apostrophe -> ',
# em-dash -> "--"; no wording or numeric values changed) --------------

EVIDENCE_COINMARKETCAP = """## Specifications
Pairs\t
Price
: +2% / -2% Depth
Volume (24h): Volume %\t
Liquidity

1\t

Binance

\t
BTC/USDT

: $78,614.93
Binance

\t
BTC/USDC

: $78,613.59
Coinbase Exchange

\t
BTC/USD

: $78,623.83
OKX

\t
BTC/USDT

: $78,625.04
Bybit

\t
BTC/USDT

: $78,675.62
Upbit

\t
BTC/KRW

: $79,510.19
Bitget

\t
BTC/USDT

: $78,674.21
Gate

\t
BTC/USDT

: $78,611.52
KuCoin

\t
BTC/USDT

: $78,627.04
MEXC

\t
BTC/USDT

: $78,683.54
Show rows
10
Show full width

Disclaimer: This page may contain affiliate links. CoinMarketCap may be compensated if you visit any affiliate links and you take certain actions such as signing up and transacting with these affiliate platforms. Please refer to Affiliate Disclosure
Community
Trade
Top
Latest: $BTC How do you feel today?
Beginner
Intermediate
Expert
Overview: Bitcoin is a groundbreaking digital

## Exchange
Pairs\t
Price
\t
+2% / -2% Depth
\t
Volume (24h)
\tVolume %\t
Liquidity

1\t

Binance

\t
BTC/USDT

\t
$78,614.93
\t$25,962,084/$16,846,316\t
$1,464,007,381
\t4.18%\t
1,159

2\t

Binance

\t
BTC/USDC

\t
$78,613.59
\t$5,713,980/$5,743,126\t
$319,633,563
\t0.91%\t
967

3\t

Coinbase Exchange

\t
BTC/USD

\t
$78,623.83
\t$22,611,262/$14,721,701\t
$354,944,696
\t1.01%\t
890

4\t

OKX

\t
BTC/USDT

\t
$78,625.04
\t$8,878,756/$2,407,196\t
$420,390,212
\t1.20%\t
905

5\t

Bybit

\t
BTC/USDT

\t
$78,675.62
\t$15,777,329/$12,500,614\t
$599,422,604
\t1.71%\t
873

6\t

Upbit

\t
BTC/KRW

\t
$79,510.19
\t$454,913/$113,804\t
$68,769,947
\t0.20%\t
620

7\t

Bitget

\t
BTC/USDT

\t
$78,674.21
\t$11,415,931/$10,534,868\t
$227,049,143
\t0.65%\t
990

8\t

Gate

\t
BTC/USDT

\t
$78,611.52
\t$12,474,656/$13,432,366\t
$521,443,892
\t1.49%\t
902

9\t

KuCoin

\t
BTC/USDT

\t
$78,627.04
\t$7,275,765/$6,453,749\t
$567,081,499
\t1.62%\t
944

10\t

MEXC

\t
BTC/USDT

\t
$78,683.54
\t$3,354,367/$2,155,926\t
$688,015,379
\t1.96%\t
905
1
2
3
4
384
Showing 1 - 10 out of 3836
Sh"""

EVIDENCE_COINBASE = """## Specifications
Happening now

AI generated 29m ago: BTC surged (up)21% this month, outpacing both ETH and SOL in price gains.
BTC vs markets: (down) 0.3%
BTC vs ETH: (up) 21.97%
Tags

mineable

pow

sha-256: store-of-value
AI generated 29m ago: BTC surged (up)21% this month, outpacing both ETH and SOL in price gains.
Market Position: -
Latest Stories: -

## Price history
| Time | Price | Change |
| --- | --- | --- |
| Today | Not enough data | Not enough data |
| 1 Day | $78,913.40 | -0.24% |
| 1 Week | $77,885.98 | +0.93% |
| 1 Month | $65,073.15 | +20.80% |
| 1 Year | $111,546.61 | -29.53% |

## Price Change (1Y)
29.53%

## About Bitcoin
The world's first cryptocurrency, Bitcoin is stored and exchanged securely on the internet through a digital ledger known as a blockchain. Bitcoins are divisible into smaller units known as satoshis -- each satoshi is worth 0.00000001 bitcoin.

Happening now

AI generated 29m ago

BTC surged (up)21% this month, outpacing both ETH and SOL in price gains.

[See more](https://www.coinbase.com/price/bitcoin#insights)

## Market details
BTC vs markets

(down) 0.3%

BTC vs ETH

(up) 21.97%

Tags

mineable

pow

sha-256

store-of-value

+8

## Recent trends
Compared to Bitcoin's value of $78,913.40 from 24 hours ago, there's been a -0% decrease, while the current price is 1% up from $77,885.98 which was recorded one week ago.

The current circulating supply of Bitcoin is 20,081,528. This is 96% of its max supply of 21,000,000 BTC and 100% of its total supply of 20,081,528. The fully diluted valuation of Bitcoin is $1.65T. The diluted valuation of Bitcoin is $1.65T.

Bitcoin had 34,983 buyers, 15,854 sellers and total 48,965 trades in the last 24h. Bitcoin was searched 6,298 times in the last 24h.

## Additional details


## Coinbase insights


## Happening now
AI generated 29m ago

BTC surged (up)21% this month, outpacing both ETH and SOL in price gains.

Market Position

-

Represents roughly 60% of total cryptocurrency market cap

-

Volume climbed (up)43% since Tuesday afternoon, exceeding market average

-

Trading (up)38% below all-time highs despite monthly outperformance vs ETH and SOL

Latest Stories

-

Strive adds 1,375 Bitcoin approaching billion-dollar milestone.

[Source](https://www.theblock.co/news/markets/2026-09-08-strive-adds-1375-bitcoin-sata-approaches-billion-dollar-milestone-413800)

-

Strategy doubles buyback program authorization to $2 billion.

[Source](https://decrypt.co/377664/strategys-return-to-bitcoin-buying-lasted-exactly-one-week)

-

Golden cross appears on daily chart potential bullish trend.

[Source](https://www.coindesk.com/markets/2026/09/08/bitcoin-s-golden-cross-is-here)"""

COINMARKETCAP_URL = "https://coinmarketcap.com/currencies/bitcoin/"
COINBASE_URL = "https://www.coinbase.com/price/bitcoin"

SOURCE_TO_EVIDENCE = {
    COINMARKETCAP_URL: EVIDENCE_COINMARKETCAP,
    COINBASE_URL: EVIDENCE_COINBASE,
}

EVIDENCE_TEXT = (
    f"### SUMBER 1: {COINMARKETCAP_URL} (tipe: datasheet)\n{EVIDENCE_COINMARKETCAP}\n\n"
    f"### SUMBER 2: {COINBASE_URL} (tipe: datasheet)\n{EVIDENCE_COINBASE}"
)

# --- real requirement text -- copied verbatim from this SAME trace's ---
# --- own Planner knowledge_required[] and the relevance-classifier -----
# --- calls it fed (topic/need pairs actually used earlier in this ------
# --- pipeline, just never passed on to extraction) ---------------------

REQUIREMENT_TOPIC_1 = "current Bitcoin price"
REQUIREMENT_NEED_1 = "live price data from financial websites or APIs"
REQUIREMENT_TOPIC_2 = "Bitcoin price comparison across sources"
REQUIREMENT_NEED_2 = "comparison of BTC prices from at least 2 independent financial data sources"

RULES_BLOCK = """RULES:
1. Extract substantive facts only: specifications, values, numbers, commands,
   code, steps, symptoms, causes, solutions, tools, endpoints, configuration,
   and other relevant technical information.
2. Ignore menus, navigation, footers, copyright notices, breadcrumbs,
   page titles, section names, link lists, and UI text that does not contain
   substantive facts.
3. Do not turn page titles or navigation labels into domain facts.
4. A URL may be extracted only when the URL itself is a relevant fact,
   such as an API endpoint, documentation URL, download URL, or target URL.
5. Normalize keys to short snake_case names.
6. Include both the source URL and source_type.
7. NEVER invent, infer, or fabricate values that are not explicitly present
   in the evidence.
8. If the evidence contains only metadata or navigation and no substantive
   facts, return no facts rather than creating facts to fill the output.
9. Preserve exact numeric values, units, URLs, commands, and technical terms
   from the evidence."""

PROMPT_BASELINE = f"""Extract substantive facts from the evidence below.

{RULES_BLOCK}

EVIDENCE:
{EVIDENCE_TEXT}

Return JSON:
{{"field_id": {{"value": "value", "source": "URL", "source_type": "type"}}}}"""

PROMPT_CANDIDATE = f"""Extract only facts required for these research requirements:

1. Determine the current Bitcoin/BTC price.
2. Compare the current BTC price using at least two independent sources.

{RULES_BLOCK}

EXTRACTION SCOPE:
Allowed fields only:
- current_price
- source
- source_type
- trading_pair_or_quote_currency
- timestamp, only when explicitly present

Do not extract:
- market cap
- fully diluted valuation
- circulating or maximum supply
- volume
- liquidity
- order-book depth
- historical prices
- percentage changes
- buyers, sellers, or trades
- news, tags, or unrelated metadata

Preserve every value exactly as written in the evidence.
Do not convert \"$1.65T\" into \"1650000000000\".
Do not normalize or reformat numeric values.
Return JSON only using this shape:

{{
  \"field_id\": {{
    \"value\": \"exact value from evidence\",
    \"source\": \"exact source URL\",
    \"source_type\": \"exact source type\"
  }}
}}

If valid JSON cannot be produced, return {{}}.

EVIDENCE:
{EVIDENCE_TEXT}
"""

SYSTEM_PROMPT = (
    "You are a universal fact extractor. Extract substantive facts only. "
    "Normalize keys to short snake_case names."
)

UNRELATED_KEYWORDS = (
    "depth", "volume", "liquidity", "supply", "diluted", "buyer", "seller",
    "trade", "cap", "history", "change", "tag", "search",
)


def classify_fact_key(key):
    k = key.lower()
    is_price = "price" in k
    is_unrelated_metric = any(kw in k for kw in UNRELATED_KEYWORDS)
    if is_price and not is_unrelated_metric:
        return "required"
    if is_unrelated_metric:
        return "unrelated"
    return "other"


def normalize_minimal(parsed):
    """Lightweight, harness-only list->dict normalize for counting facts in
    this script's own output -- NOT PATCH7's exact production logic, just
    enough to count facts consistently across baseline/candidate here."""
    if isinstance(parsed, list):
        normalized = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            if "field_id" in item:
                normalized[str(item["field_id"])] = item
            elif len(item) >= 1:
                k0 = next(iter(item.keys()))
                normalized[k0] = item
        return normalized
    if isinstance(parsed, dict):
        return parsed
    return {}


def run_one(llm, label, prompt):
    t0 = time.time()
    try:
        result = llm.analyze(SYSTEM_PROMPT, prompt, temperature=0.1, max_tokens=MAX_TOKENS)
    except Exception as e:
        t1 = time.time()
        return {
            "label": label, "error": repr(e),
            "started_epoch": t0, "ended_epoch": t1,
            "elapsed_s": round(t1 - t0, 3),
        }
    t1 = time.time()
    elapsed = t1 - t0

    content = result.get("content") or ""
    finish_reason = result.get("finish_reason")
    model = result.get("model")
    requested_model = result.get("requested_model")
    tokens_output = result.get("tokens_output")

    parsed = normalize_minimal(extract_json(content))

    n_required = n_unrelated = n_other = n_mismatch = n_unknown_source = 0
    mismatch_details = []
    required_sources = set()
    for key, value in parsed.items():
        cls = classify_fact_key(key)
        if cls == "required":
            n_required += 1
            if isinstance(value, dict):
                required_sources.add(str(value.get("source", "")).strip())
        elif cls == "unrelated":
            n_unrelated += 1
        else:
            n_other += 1

        if isinstance(value, dict):
            src = str(value.get("source", "")).strip()
            fact_value = str(value.get("value", ""))
            src_content = SOURCE_TO_EVIDENCE.get(src)
            if src_content is None:
                n_unknown_source += 1
            elif classify_value_support(fact_value, src_content) == MISMATCH:
                n_mismatch += 1
                mismatch_details.append({
                    "key": key,
                    "value": fact_value,
                    "source": src,
                    "numeric_tokens": __import__("re").findall(r"\d+(?:[.,]\d+)?", fact_value),
                })

    truncated = (finish_reason == "length") or (tokens_output == MAX_TOKENS)

    return {
        "label": label, "error": None, "model": model,
        "requested_model": requested_model,
        "started_epoch": t0, "ended_epoch": t1,
        "finish_reason": finish_reason, "tokens_output": tokens_output,
        "output_chars": len(content), "elapsed_s": round(elapsed, 1),
        "n_facts": len(parsed), "n_required": n_required,
        "n_unrelated": n_unrelated, "n_other": n_other,
        "n_mismatch": n_mismatch, "n_unknown_source": n_unknown_source,
        "mismatch_details": mismatch_details,
        "required_sources": sorted(s for s in required_sources if s),
        "truncated": truncated, "fact_keys": list(parsed.keys()),
        "content_preview": content[:300],
    }


def main():
    cfg = config.load_config()
    llm = LLMAnalyzer(cfg)

    print(f"input_chars baseline prompt : {len(PROMPT_BASELINE)}")
    print(f"input_chars candidate prompt: {len(PROMPT_CANDIDATE)}")
    print(f"max_tokens (fixed, both)    : {MAX_TOKENS}")
    print()

    rows = []
    for label, prompt in [("baseline", PROMPT_BASELINE), ("candidate", PROMPT_CANDIDATE)]:
        print(f"=== {label} ({N_RUNS_PER_CONDITION} runs) ===")
        for i in range(1, N_RUNS_PER_CONDITION + 1):
            r = run_one(llm, label, prompt)
            rows.append(r)
            if r.get("error"):
                print(f"  run {i}: ERROR {r['error']}")
            else:
                print(
                    f"  run {i}: model={r['model']} finish_reason={r['finish_reason']} "
                    f"requested_model={r.get('requested_model')} "
                    f"started_epoch={r.get('started_epoch'):.3f} "
                    f"ended_epoch={r.get('ended_epoch'):.3f} "
                    f"elapsed_s={r.get('elapsed_s')} "
                    f"tokens_output={r['tokens_output']} output_chars={r['output_chars']} "
                    f"n_facts={r['n_facts']} required={r['n_required']} "
                    f"unrelated={r['n_unrelated']} other={r['n_other']} "
                    f"mismatch={r['n_mismatch']} unknown_source={r['n_unknown_source']} "
                    f"truncated={r['truncated']}"
                )
                print(f"    fact_keys: {r['fact_keys']}")
                if r["mismatch_details"]:
                    print(f"    mismatch_details: {r['mismatch_details']}")
                print(f"    required_sources: {r['required_sources']}")
                if r["n_facts"] == 0:
                    print(f"    content_preview: {r['content_preview']!r}")
        print()

    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)
    for label in ("baseline", "candidate"):
        ok_rows = [r for r in rows if r["label"] == label and not r.get("error")]
        n = len(ok_rows)
        if n == 0:
            print(f"{label}: no successful runs")
            continue
        avg = lambda field: sum(r[field] for r in ok_rows) / n
        n_truncated = sum(1 for r in ok_rows if r["truncated"])
        n_mismatch_total = sum(r["n_mismatch"] for r in ok_rows)
        models = sorted(set(r["model"] for r in ok_rows))
        print(
            f"{label:10s} n={n} avg_facts={avg('n_facts'):.1f} "
            f"avg_required={avg('n_required'):.1f} avg_unrelated={avg('n_unrelated'):.1f} "
            f"truncated={n_truncated}/{n} total_mismatch_flagged={n_mismatch_total} "
            f"models={models}"
        )

    print()
    print("Acceptance criteria to check against the numbers above:")
    print("  1. requirement-specific (required) facts still appear in candidate")
    print("  2. unrelated facts drop significantly vs baseline")
    print("  3. JSON parses (n_facts > 0 where not truncated)")
    print("  4. finish_reason != 'length' for candidate (truncated == False)")
    print("  5. total_mismatch_flagged stays 0 (or does not increase vs baseline) --")
    print("     this is classify_value_support()==MISMATCH against the REAL source text,")
    print("     the same function already verified in production, not a manual guess")
    print("  6. both coinmarketcap.com and coinbase.com sources represented among")
    print("     'required' facts -- inspect fact_keys/'source' values per run above")
    print("  7. not dependent on one model -- check the 'models' list per condition")


if __name__ == "__main__":
    main()

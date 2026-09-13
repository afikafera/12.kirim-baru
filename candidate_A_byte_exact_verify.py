"""
Verify candidate A's Rule 1 against the REAL, byte-exact evidence
(reused from btc_trace_replay.py's build_evidence(), not a
hand-abridged excerpt) for both facts this whole investigation cares
about: current_price_usd (the one that failed under BASELINE) and
price_usd_coindesk (already working, must not regress).

Still NOT a patch -- this only proves candidate A's logic against real
bytes before any change is made to hermes_agent/fact_checker.py.

Run:
    cd ~/research-assistant
    python3 candidate_A_byte_exact_verify.py
"""
import re
import sys

sys.path.insert(0, ".")

from btc_trace_replay import build_evidence
from step3_newline_boundary_audit import resolve_ambiguous_variant, _rule1_candidate_A, ACCEPT_CONTEXTUAL
from patch1_step2_classifier_harness import classify_value_support, AMBIGUOUS, UNAMBIGUOUS_NORMALIZED, EXACT

all_evidence = build_evidence()
by_url = {e["url"]: e["content"] for e in all_evidence}

TRADINGVIEW_URL = "https://id.tradingview.com/symbols/BTCUSD/"
COINDESK_URL = "https://www.coindesk.com/id/price/bitcoin"

print(f"TradingView content length: {len(by_url[TRADINGVIEW_URL])} chars")
print(f"CoinDesk content length: {len(by_url[COINDESK_URL])} chars")
print()

cases = [
    ("current_price_usd", "78347", by_url[TRADINGVIEW_URL]),
    ("price_usd_coindesk", "78378.18", by_url[COINDESK_URL]),
]

for label, value, source in cases:
    step2 = classify_value_support(value, source)
    print(f"{label}: Step2 = {step2}")
    if step2 == AMBIGUOUS:
        result = resolve_ambiguous_variant(value, source, _rule1_candidate_A)
        print(f"  -> resolve_ambiguous (candidate A) = {result}")
        print(f"  -> {'PASS' if result == ACCEPT_CONTEXTUAL else 'STILL BROKEN'}")
    else:
        print(f"  -> not AMBIGUOUS, goes straight to PATCH2 check (unaffected by candidate A) -- ACCEPT expected")
    print()

# Sanity: also re-confirm the synthetic double-newline case still rejects
# using this same real-data pipeline's imports, not just the earlier
# standalone harness run.
synthetic_double_nl = "78.347\n\nUSD"
r = resolve_ambiguous_variant("78347", synthetic_double_nl, _rule1_candidate_A)
print(f"Sanity (synthetic double-newline, must NOT accept): {r}")

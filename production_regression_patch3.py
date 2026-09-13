"""
PATCH 3 -- production regression (post-apply).

Imports classify_value_support, resolve_ambiguous, _value_is_example_scoped,
and the state constants DIRECTLY from the now-patched hermes_agent.fact_checker
-- not from the standalone scratch scripts used during design. This is the
step that proves the code hand-transcribed into apply_patch3_locale_context.py
behaves EXACTLY like what was already verified in isolation, not just "looks
the same" by inspection.

Re-runs, against the real production import:
  A. Step 2 numeric classifier matrix (abstract cases + all 22 real
     trace-01f3a9ee... fields)
  B. PATCH2 example-scope matrix (7 cases; production _value_is_example_scoped
     is now itself the fixed version, so this checks production directly,
     no separate OLD/CANDIDATE split needed anymore)
  C. Step 3 contextual resolver matrix (8 contract cases + 2 real BTC facts +
     2 adversarial + window sweep 50/100/200/300/500)
  D. Full integration matrix (the 7 cases from integration_harness.py)

This does NOT yet replay the real BTC trace end-to-end through
extract_facts_batch() with a FakeLLM (that is the next, separate step), and
does not touch "full 80/80" (please clarify what that suite is / where it
lives -- not something in this conversation's history).

Run:
    cd ~/research-assistant
    python3 production_regression_patch3.py
"""
import sys

sys.path.insert(0, ".")

from hermes_agent.fact_checker import (
    classify_value_support,
    resolve_ambiguous,
    _value_is_example_scoped,
    EXACT,
    UNAMBIGUOUS_NORMALIZED,
    AMBIGUOUS,
    MISMATCH,
    ACCEPT_CONTEXTUAL,
    REJECT_CONTEXTUAL,
    UNRESOLVED,
    WINDOW_CHARS,
)

ACCEPT = "ACCEPT"
REJECT = "REJECT"

overall_fail = 0


def check(section, label, actual, expected):
    global overall_fail
    ok = actual == expected
    if not ok:
        overall_fail += 1
    tag = "ok" if ok else f"FAIL (got {actual!r}, expected {expected!r})"
    print(f"  [{section}] {label:55s} {tag}")
    return ok


# =======================================================================
# A. Step 2 numeric classifier
# =======================================================================
print("=" * 100)
print("A. STEP 2 NUMERIC CLASSIFIER (production import)")
print("=" * 100)

ABSTRACT_CASES = [
    ("mixed_sep", "78378.18", "78.378,18", UNAMBIGUOUS_NORMALIZED),
    ("single_sep_2dig", "3.13", "3,13", UNAMBIGUOUS_NORMALIZED),
    ("multi_group", "1507904", "1,507,904", UNAMBIGUOUS_NORMALIZED),
    ("single_sep_2dig_pct", "0.70", "0,70%", UNAMBIGUOUS_NORMALIZED),
    ("ambiguous_dot_short", "78347", "78.347", AMBIGUOUS),
    ("ambiguous_comma_3dig", "966030", "966,030", AMBIGUOUS),
    ("ambiguous_dot_1234", "1234", "1.234", AMBIGUOUS),
    ("ambiguous_comma_1234", "1234", "1,234", AMBIGUOUS),
    ("exact_literal_1234", "1.234", "1.234", EXACT),
    ("candidate_has_comma", "1,234", "1.234", AMBIGUOUS),
    ("real_mismatch", "78347", "78348", MISMATCH),
    ("fabricated_no_digits", "12", "no numbers here at all", MISMATCH),
    ("multi_digit_fraction", "0.0058", "Funding Rate: 0,0058%", UNAMBIGUOUS_NORMALIZED),
]
for label, value, source, expected in ABSTRACT_CASES:
    check("Step2-abstract", label, classify_value_support(value, source), expected)

TRACE_FIELDS = [
    ("current_price_usd", "78347", "Harga Bitcoin (BTC) saat ini adalah: 78.347 USD", AMBIGUOUS),
    ("price_change_24h_percent", "-0.94", "telah turun sebesar -0,94% dalam 24 jam terakhir", UNAMBIGUOUS_NORMALIZED),
    ("price_change_7d_percent", "0.25", "Harga Bitcoin telah naik sebesar: 0,25", UNAMBIGUOUS_NORMALIZED),
    ("price_change_1y_percent", "-29.54", "Bitcoin mengalami penurunan sebesar: -29,54", UNAMBIGUOUS_NORMALIZED),
    ("market_cap_usd", "1.57T", "Kapitalisasi pasar: 1,57 T USD", UNAMBIGUOUS_NORMALIZED),
    ("fully_diluted_market_cap_usd", "1.64T", "Cap Pasar Terdilusi Sepenuhnya: 1,64 T USD", UNAMBIGUOUS_NORMALIZED),
    ("circulating_supply", "20.08M", "Suplai sirkulasi: 20,08 M", UNAMBIGUOUS_NORMALIZED),
    ("max_supply", "21.00M", "Suplai maksimum: 21,00 M", UNAMBIGUOUS_NORMALIZED),
    ("total_supply", "20.08M", "Total suplai: 20,08 M", UNAMBIGUOUS_NORMALIZED),
    ("open_interest_usd", "26.41B", "Minat terbuka 26,41 B USD 0,93%", UNAMBIGUOUS_NORMALIZED),
    ("liquidations_24h_usd", "21.88M", "Likuidasi (24h) 21,88 M USD", UNAMBIGUOUS_NORMALIZED),
    ("funding_rate_percent", "0.0058", "Funding Rate: 0,0058%", UNAMBIGUOUS_NORMALIZED),
    ("trading_volume_24h_usd", "23.40B", "volume trading Bitcoin (BTC) dalam 24 jam adalah 23,40 B USD", UNAMBIGUOUS_NORMALIZED),
    ("price_change_1m_percent", "21.36", "kinerja bulannya menunjukkan peningkatan sebesar 21,36 %", UNAMBIGUOUS_NORMALIZED),
    ("price_usd_coindesk", "78378.18", "Bitcoin BTC #1 $78.378,18 Turun 1,35 persen", UNAMBIGUOUS_NORMALIZED),
    ("block_number", "966030", "Nomor Blok 966,030", AMBIGUOUS),
    ("block_reward", "3.13", "Hadiah Blok 3,13", UNAMBIGUOUS_NORMALIZED),
    ("last_block_size", "1507904", "Ukuran Blok Terakhir 1,507,904", UNAMBIGUOUS_NORMALIZED),
    ("volume_to_market_cap_ratio_24h_percent_coindesk", "0.70", "Vol/Kap. Pasar (24j) 0,70%", UNAMBIGUOUS_NORMALIZED),
    ("exchange_prices",
     "Binance: 78389.16 USDT (-1.31%), Bybit: 78391.60 USDT (-1.31%), Gateio: 78396.80 USDT, Okex: 78388.80 USDT, Bullish: 78360.07 USDC (-1.36%)",
     "BTC-USDT BTCUSDT Binance AA : 78.389,16 USDT: -1,31% BTC-USDT BTCUSDT Bybit A : 78.391,60 BTC-USDT BTC_USDT Gateio A : 78.396,80 BTC-USDT BTC-USDT Okex A : 78.388,80 BTC-USDC BTCUSDC Bullish AA : 78.360,07 USDC: -1,36%",
     UNAMBIGUOUS_NORMALIZED),
    ("market_cap_usd_coindesk", "1.57T", "Kapitalisasi Pasar $1.57T Turun 1,35 persen", EXACT),
    ("total_supply_coindesk", "20.08M BTC", "Total Pasokan 20.08M BTC", EXACT),
    ("fabricated_port_width", "12-inch", "This enclosure ships in three trim colors and a padded travel case.", MISMATCH),
]
for label, value, source, expected in TRACE_FIELDS:
    check("Step2-trace", label, classify_value_support(value, source), expected)


# =======================================================================
# B. PATCH2 example-scope gate (production is now the fixed version)
# =======================================================================
print()
print("=" * 100)
print("B. PATCH2 EXAMPLE-SCOPE (production _value_is_example_scoped)")
print("=" * 100)

PATCH2_CASES = [
    ("marker_before_value", "1.5 cf", "For example, this measurement of 1.5 cf net is used in the formula.", True),
    ("marker_after_value_same_clause", "1.5 cf", "This measurement of 1.5 cf net is just an example for illustration.", True),
    ("no_marker_control", "1.5 cf", "This measurement of 1.5 cf net is the actual product specification.", False),
    ("integer_value_marker_after_scope_control", "78347", "The reported count is 78347, for example, in typical usage.", True),
    ("regression_marker_in_next_clause", "1.5 cf", "The value is 1.5 cf. For example, other units use 2.0 cf.", False),
    ("semicolon_boundary", "1.5 cf", "The measurement is 1.5 cf; for example, other configurations differ.", False),
    ("known_limitation_multi_occurrence_real_then_example", "1.5 cf",
     "The product uses 1.5 cf net for the main chamber. "
     "For example, a smaller model might use 1.5 cf net for a secondary chamber.", False),
]
for label, value, source, expected in PATCH2_CASES:
    check("PATCH2", label, _value_is_example_scoped(value, source), expected)


# =======================================================================
# C. Step 3 contextual resolver
# =======================================================================
print()
print("=" * 100)
print("C. STEP 3 CONTEXTUAL RESOLVER (production import)")
print("=" * 100)

TRADINGVIEW_EXCERPT = (
    "Harga Bitcoin (BTC) saat ini adalah: 78.347 USD: . Temukan lebih banyak "
    "wawasan pada volume trading Bitcoin (BTC) dalam 24 jam adalah Harga Bitcoin "
    "telah naik sebesar: 0,25 Bitcoin mengalami penurunan sebesar: -29,54 Bitcoin "
    "(BTC: ) mencapai harga terendahnya sebesar USD pada 20 Okt 2011: . Lihat lebih "
    "banyak dinamika Bitcoin: pada chart harga. Kapitalisasi pasar: 1,57 T USD Cap "
    "Pasar Terdilusi Sepenuhnya: 1,64 T USD Suplai sirkulasi: 20,08 M Suplai "
    "maksimum: 21,00 M"
)
COINDESK_STATBOX_EXCERPT = (
    "Statistik Utama Kapitalisasi Pasar $1.57T Turun 1,35 persen 1,35% Volume "
    "(24j) $11.08B Nilai Terdilusi Penuh $1.65T Vol/Kap. Pasar (24j) 0,70% Total "
    "Pasokan 20.08M BTC Pasokan Maksimum 21.00M BTC Pasokan Beredar 20.08M BTC "
    "Tanggal Peluncuran 2009-01-03 Nomor Blok 966,030 Hadiah Blok 3,13 Ukuran "
    "Blok Terakhir 1,507,904 Jaringan H/s 868884085.20T"
)

STEP3_CASES = [
    ("CASE1_price_usd_label", "78347", "Bitcoin Price: 78.347 USD", ACCEPT_CONTEXTUAL),
    ("CASE2_block_number_isolated", "966030", "Nomor Blok: 966,030", UNRESOLVED),
    ("CASE3_value_bare", "1234", "Value: 1.234", UNRESOLVED),
    ("CASE4_value_with_usd", "1234", "Value: 1.234 USD", ACCEPT_CONTEXTUAL),
    ("CASE5_price_bare", "1234", "Price: 1.234", UNRESOLVED),
    ("CASE6_mixed_sep_not_really_ambiguous", "1234.56", "Price: 1.234,56 USD", UNRESOLVED),
    ("CASE7_wrong_value_not_really_ambiguous", "966031", "Block Number: 966,030", UNRESOLVED),
    ("CASE_example_scope_override", "1234", "Example price: 1.234 USD", REJECT_CONTEXTUAL),
    ("REAL_current_price_usd_tradingview", "78347", TRADINGVIEW_EXCERPT, ACCEPT_CONTEXTUAL),
    ("REAL_block_number_coindesk_statbox", "966030", COINDESK_STATBOX_EXCERPT, ACCEPT_CONTEXTUAL),
    ("ADV_conflicting_precedent_far", "1234", "Change: -1,31 percent. Unrelated value: 1,234 here.", UNRESOLVED),
    ("ADV_currency_far_away_unrelated", "1234",
     "Total revenue this year was reported at $500,000. In an unrelated note, "
     "the counter shows: 1,234 units in stock.", UNRESOLVED),
]
for label, value, source, expected in STEP3_CASES:
    check("Step3", label, resolve_ambiguous(value, source), expected)

print(f"  [Step3] WINDOW_CHARS in production = {WINDOW_CHARS}")
WINDOW_SWEEP = [50, 100, 200, 300, 500]
sweep_targets = [
    ("REAL_block_number_coindesk_statbox", "966030", COINDESK_STATBOX_EXCERPT),
    ("REAL_current_price_usd_tradingview", "78347", TRADINGVIEW_EXCERPT),
    ("ADV_conflicting_precedent_far", "1234", "Change: -1,31 percent. Unrelated value: 1,234 here."),
    ("ADV_currency_far_away_unrelated", "1234",
     "Total revenue this year was reported at $500,000. In an unrelated note, "
     "the counter shows: 1,234 units in stock."),
]
for label, value, source in sweep_targets:
    row = [resolve_ambiguous(value, source, window_chars=w) for w in WINDOW_SWEEP]
    sensitive = len(set(row)) > 1
    print(f"  [Step3-sweep] {label:45s} {row} {'SENSITIVE' if sensitive else 'stable'}")


# =======================================================================
# D. Full integration (Step2 -> PATCH2 -> Step3), production import
# =======================================================================
print()
print("=" * 100)
print("D. FULL INTEGRATION CHAIN (production import)")
print("=" * 100)


def decide(value, source_content):
    step2 = classify_value_support(value, source_content)
    trace = {"step2": step2}

    if step2 == MISMATCH:
        return REJECT, trace

    if step2 in (EXACT, UNAMBIGUOUS_NORMALIZED):
        if _value_is_example_scoped(value, source_content):
            trace["patch2"] = "REJECTED"
            return REJECT, trace
        trace["patch2"] = "PASS"
        return ACCEPT, trace

    step3 = resolve_ambiguous(value, source_content)
    trace["step3"] = step3
    if step3 == ACCEPT_CONTEXTUAL:
        return ACCEPT, trace
    return REJECT, trace


INTEGRATION_CASES = [
    ("SCENARIO1_example_usd_marker_after_directional", "1234",
     "The price of 1.234 USD is just an example, not the actual value.", REJECT),
    ("SCENARIO1b_example_usd_marker_before", "1234", "Example price: 1.234 USD", REJECT),
    ("SCENARIO2_real_current_price_usd", "78347", TRADINGVIEW_EXCERPT, ACCEPT),
    ("SCENARIO3_real_block_number", "966030", COINDESK_STATBOX_EXCERPT, ACCEPT),
    ("SCENARIO4_ambiguous_no_context", "1234", "Value: 1.234", REJECT),
    ("EXTRA_mismatch", "78347", "The reported figure was 78348, a completely different number.", REJECT),
    ("EXTRA_direct_path_real_coindesk_price", "78378.18", "Bitcoin BTC #1 $78.378,18 Turun 1,35 persen", ACCEPT),
]
for label, value, source, expected in INTEGRATION_CASES:
    final, trace = decide(value, source)
    ok = check("Integration", label, final, expected)
    if not ok:
        print(f"      trace: {trace}")


print()
print("=" * 100)
if overall_fail == 0:
    print("ALL SECTIONS PASS against the PRODUCTION import.")
else:
    print(f"{overall_fail} MISMATCH(ES) -- do not proceed, investigate before calling this VERIFIED.")
print("=" * 100)

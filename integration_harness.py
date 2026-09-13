"""
Full integration harness (2026-09-08): chains Step 2 (numeric fidelity
classifier) -> PATCH2 example-scope override (CANDIDATE fix) -> Step 3
(contextual disambiguation for AMBIGUOUS facts) into one final ACCEPT /
REJECT decision per fact.

STILL NOT a production patch. This only proves the pieces compose
correctly, per the exact chain specified 2026-09-08:

    Step 2 classifier
        |
        +-- EXACT / UNAMBIGUOUS_NORMALIZED --> PATCH2 check --> ACCEPT/REJECT
        +-- MISMATCH --> REJECT (fail-closed; no context can save a
        |                genuine mismatch, Step 3 never even runs)
        +-- AMBIGUOUS --> Step 3 (which itself runs PATCH2-CANDIDATE as
                          its own Rule 0, then Rule 1 / Rule 2)
                          --> ACCEPT_CONTEXTUAL / REJECT_CONTEXTUAL / UNRESOLVED
                          --> mapped to final ACCEPT / REJECT
                              (UNRESOLVED maps to REJECT: fail-closed
                              default when no context proof exists
                              either way)

Requires patch1_step2_classifier_harness.py, patch2_example_scope_audit.py,
and patch1_step3_context_harness.py in the same directory (the latter two
also need the real fact_checker.py to resolve their own imports).

Run:
    cd ~/research-assistant
    python3 integration_harness.py
"""
import sys

sys.path.insert(0, ".")

from patch1_step2_classifier_harness import (
    classify_value_support, EXACT, UNAMBIGUOUS_NORMALIZED, MISMATCH,
)
from patch2_example_scope_audit import CANDIDATE as example_scoped
from patch1_step3_context_harness import (
    resolve_ambiguous, ACCEPT_CONTEXTUAL, REJECT_CONTEXTUAL, UNRESOLVED,
)

ACCEPT = "ACCEPT"
REJECT = "REJECT"


def decide(value: str, source_content: str):
    """Returns (final_decision, trace) where trace documents every
    intermediate stage's verdict, for auditability."""
    step2 = classify_value_support(value, source_content)
    trace = {"step2": step2}

    if step2 == MISMATCH:
        trace["reason"] = "no supporting evidence in source under any interpretation -- fail closed"
        return REJECT, trace

    if step2 in (EXACT, UNAMBIGUOUS_NORMALIZED):
        if example_scoped(value, source_content):
            trace["patch2"] = "REJECTED (example-scoped)"
            return REJECT, trace
        trace["patch2"] = "PASS"
        return ACCEPT, trace

    # AMBIGUOUS
    step3 = resolve_ambiguous(value, source_content)
    trace["step3"] = step3
    if step3 == ACCEPT_CONTEXTUAL:
        return ACCEPT, trace
    if step3 == REJECT_CONTEXTUAL:
        return REJECT, trace
    trace["reason"] = "ambiguous, no contextual proof either way -- fail closed"
    return REJECT, trace


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

# ---------------------------------------------------------------------
# The four scenarios from the 2026-09-08 integration-matrix spec, plus
# two extra cases (MISMATCH, and a non-ambiguous direct-accept sanity
# check) for completeness.
# ---------------------------------------------------------------------
CASES = [
    ("SCENARIO1_example_usd_marker_after_directional",
     "1234",
     "The price of 1.234 USD is just an example, not the actual value.",
     REJECT,
     "Marker AFTER value, same clause -- the exact directional bug pattern "
     "found in PATCH2. PATCH2-CANDIDATE must reject; Rule 1 (currency) must "
     "NOT be allowed to override it. This is the critical regression check: "
     "if Step 3 still used OLD's buggy PATCH2, this case would wrongly ACCEPT."),

    ("SCENARIO1b_example_usd_marker_before",
     "1234",
     "Example price: 1.234 USD",
     REJECT,
     "Same intent, marker before value (already-known-good pattern) -- sanity control."),

    ("SCENARIO2_real_current_price_usd",
     "78347",
     TRADINGVIEW_EXCERPT,
     ACCEPT,
     "Step2 AMBIGUOUS, no example marker anywhere, Rule 1 (USD adjacency) fires -> ACCEPT."),

    ("SCENARIO3_real_block_number",
     "966030",
     COINDESK_STATBOX_EXCERPT,
     ACCEPT,
     "Step2 AMBIGUOUS, no currency near 'Nomor Blok', Rule 2 (1,507,904 precedent) fires -> ACCEPT."),

    ("SCENARIO4_ambiguous_no_context",
     "1234",
     "Value: 1.234",
     REJECT,
     "Step2 AMBIGUOUS, no currency, no precedent -> Step3 UNRESOLVED -> final fail-closed REJECT."),

    ("EXTRA_mismatch",
     "78347",
     "The reported figure was 78348, a completely different number.",
     REJECT,
     "Step2 MISMATCH (no interpretation of any source token equals 78347) -> REJECT, "
     "never even reaches PATCH2 or Step3."),

    ("EXTRA_direct_path_real_coindesk_price",
     "78378.18",
     "Bitcoin BTC #1 $78.378,18 Turun 1,35 persen",
     ACCEPT,
     "Step2 UNAMBIGUOUS_NORMALIZED (mixed separators, not ambiguous at all), "
     "no example marker -> ACCEPT directly. Confirms the non-ambiguous majority "
     "of facts (18/20 in the real BTC trace) don't even need Step 3."),
]


def main():
    print(f"{'case':45s} {'final':8s} {'expected':8s} status  trace")
    print("-" * 140)
    n_ok = 0
    for label, value, source, expected, purpose in CASES:
        final, trace = decide(value, source)
        ok = final == expected
        n_ok += ok
        tag = "ok" if ok else f"MISMATCH-vs-expected(exp={expected})"
        print(f"{label:45s} {final:8s} {expected:8s} {tag:8s} {trace}")
        print(f"    purpose: {purpose}")
    print("-" * 140)
    print(f"Matches expected: {n_ok}/{len(CASES)}")


if __name__ == "__main__":
    main()

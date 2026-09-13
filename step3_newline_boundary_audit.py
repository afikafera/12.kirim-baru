"""
Step 3 newline-boundary audit (2026-09-08). Isolated reproduction +
candidate comparison. NOT a patch -- this only measures BASELINE
(current production Rule 1 clause logic) against three candidate
clause-boundary strategies (A/B/C), all under design direction D:
distinguish LAYOUT-only newlines (scraper line breaks between a number
and its immediately-adjacent unit) from SEMANTIC clause boundaries
(genuine paragraph/section breaks).

PATCH2's _value_is_example_scoped is used UNCHANGED (imported from the
real, now-patched hermes_agent.fact_checker) and is always called with
the FULL source_content, never a Step-3-sliced clause -- this decouples
Rule 0 completely from whatever clause-boundary variant is being tested
for Rule 1, satisfying "do not touch PATCH2 Rule 0" by construction,
not by promise.

Candidates (all affect ONLY Rule 1's clause computation; Rule 2 uses a
raw character window, not a clause, so it is structurally unaffected
and included in the matrix only as a regression/isolation check):

  BASELINE -- current production: '.', '!', '?', ';', '\\n' are all
              hard boundaries, single or double newline treated the same.
  A -- '.', '!', '?', ';' stay hard; a bare '\\n' is soft (skipped), but
       a blank-line run ('\\n' + optional spaces/tabs + '\\n') IS hard.
       Applied uniformly to the whole clause-boundary search.
  B -- '.', '!', '?', ';' only; newlines NEVER count as a boundary, no
       matter how many in a row.
  C -- surgical, Rule-1-only: keep BASELINE's clause as primary. If no
       currency found and the clause was cut short by exactly ONE
       newline (not a blank-line run), peek a short bounded distance
       (default 30 chars) past that single newline, stopping at the
       first hard boundary within the peek window, for a currency
       marker. Rule 2 and the base clause computation are untouched.

Run:
    cd ~/research-assistant
    python3 step3_newline_boundary_audit.py
"""
import re
import sys

sys.path.insert(0, ".")

from hermes_agent.fact_checker import (
    _value_is_example_scoped,
    _NUM_PATTERN,
)
from patch1_step2_classifier_harness import (
    _SOURCE_TOKEN_PATTERN,
    _classify_source_token,
    _parse_candidate_number,
)

ACCEPT_CONTEXTUAL = "ACCEPT_CONTEXTUAL"
REJECT_CONTEXTUAL = "REJECT_CONTEXTUAL"
UNRESOLVED = "UNRESOLVED"

WINDOW_CHARS = 300

_CURRENCY_MARKERS = re.compile(
    r'\bUSD\b|\bUSDT\b|\bUSDC\b|\bIDR\b|\bRp\b|\bEUR\b|\bGBP\b|\$',
    re.IGNORECASE,
)

_CLAUSE_BOUNDARY_CHARS = ('.', '!', '?', '\n', ';')
_HARD_BOUNDARY_A = re.compile(r'[.!?;]|\n[ \t]*\n')
_HARD_BOUNDARY_B = re.compile(r'[.!?;]')


def _find_ambiguous_occurrences(candidate_value, source_content):
    cand_f = _parse_candidate_number(candidate_value)
    if cand_f is None:
        return []
    spans = []
    for m in _SOURCE_TOKEN_PATTERN.finditer(source_content):
        readings = _classify_source_token(m.group())
        if len(readings) == 2 and any(abs(r - cand_f) < 1e-9 for r in readings):
            spans.append((m.start(), m.end(), m.group()))
    return spans


def _rule2_document_consistency(source_content, match_start, match_end, token_text, cand_f, window_chars=WINDOW_CHARS):
    sep_match = re.search(r'[.,]', token_text)
    if not sep_match:
        return False
    sep_char = sep_match.group()
    win_start = max(0, match_start - window_chars)
    win_end = min(len(source_content), match_end + window_chars)
    window = source_content[win_start:win_end]
    for m in _SOURCE_TOKEN_PATTERN.finditer(window):
        if m.group() == token_text and (win_start + m.start()) == match_start:
            continue
        if sep_char not in m.group():
            continue
        readings = _classify_source_token(m.group())
        if len(readings) != 1:
            continue
        g = re.split(r'[.,]', m.group())
        try:
            thousands_try = float("".join(g))
        except ValueError:
            thousands_try = None
        role_is_thousands = thousands_try is not None and abs(thousands_try - readings[0]) < 1e-9
        our_groups = re.split(r'[.,]', token_text)
        candidate_reading = float("".join(our_groups)) if role_is_thousands else float(f"{our_groups[0]}.{our_groups[1]}")
        if abs(candidate_reading - cand_f) < 1e-9:
            return True
    return False


# --- clause-span implementations ---------------------------------------

def _clause_span_baseline(source_content, token_start, token_end):
    start = max((source_content.rfind(c, 0, token_start) for c in _CLAUSE_BOUNDARY_CHARS), default=-1)
    end_candidates = [p for p in (source_content.find(c, token_end) for c in _CLAUSE_BOUNDARY_CHARS) if p != -1]
    end = min(end_candidates) if end_candidates else len(source_content)
    return start + 1, end + 1


def _clause_span_regex(source_content, token_start, token_end, pattern):
    clause_start = 0
    for m in pattern.finditer(source_content):
        if m.start() >= token_start:
            break
        clause_start = m.end()
    m2 = pattern.search(source_content, token_end)
    clause_end = m2.start() if m2 else len(source_content)
    return clause_start, clause_end


def _rule1_baseline(source_content, match_start, match_end):
    cs, ce = _clause_span_baseline(source_content, match_start, match_end)
    return bool(_CURRENCY_MARKERS.search(source_content[cs:ce]))


def _rule1_candidate_A(source_content, match_start, match_end):
    cs, ce = _clause_span_regex(source_content, match_start, match_end, _HARD_BOUNDARY_A)
    return bool(_CURRENCY_MARKERS.search(source_content[cs:ce]))


def _rule1_candidate_B(source_content, match_start, match_end):
    cs, ce = _clause_span_regex(source_content, match_start, match_end, _HARD_BOUNDARY_B)
    return bool(_CURRENCY_MARKERS.search(source_content[cs:ce]))


def _rule1_candidate_C(source_content, match_start, match_end, peek_chars=30):
    cs, ce = _clause_span_baseline(source_content, match_start, match_end)
    if _CURRENCY_MARKERS.search(source_content[cs:ce]):
        return True
    if ce < len(source_content) and source_content[ce] == '\n':
        if not re.match(r'\n[ \t]*\n', source_content[ce:ce + 10]):
            peek_start = ce + 1
            peek_window = source_content[peek_start:peek_start + peek_chars]
            cut = re.search(r'[.!?;\n]', peek_window)
            peek_text = peek_window[:cut.start()] if cut else peek_window
            if _CURRENCY_MARKERS.search(peek_text):
                return True
    return False


_RULE1_VARIANTS = {
    "BASELINE": _rule1_baseline,
    "A": _rule1_candidate_A,
    "B": _rule1_candidate_B,
    "C": _rule1_candidate_C,
}


def resolve_ambiguous_variant(candidate_value, source_content, rule1_fn, window_chars=WINDOW_CHARS):
    """Same orchestration as production resolve_ambiguous, except Rule 1
    is swappable. Rule 0 (PATCH2) always uses the REAL, unmodified
    _value_is_example_scoped against the FULL source_content -- never a
    Step-3-computed clause -- so it is identical across every variant."""
    cand_f = _parse_candidate_number(candidate_value)
    if cand_f is None:
        return UNRESOLVED

    occurrences = _find_ambiguous_occurrences(candidate_value, source_content)
    if not occurrences:
        return UNRESOLVED

    saw_accept = False
    for match_start, match_end, token_text in occurrences:
        if _value_is_example_scoped(token_text, source_content) or _value_is_example_scoped(candidate_value, source_content):
            return REJECT_CONTEXTUAL

        if rule1_fn(source_content, match_start, match_end):
            saw_accept = True
            continue

        if _rule2_document_consistency(source_content, match_start, match_end, token_text, cand_f, window_chars):
            saw_accept = True
            continue

    return ACCEPT_CONTEXTUAL if saw_accept else UNRESOLVED


# =========================================================================
# Test matrix, per the 2026-09-08 audit spec.
# =========================================================================
TRADINGVIEW_FULL_EXCERPT_REAL = (
    "Harga\n\nBitcoin\n\n(\n\nBTC\n\n) saat ini adalah: 78.347\n"
    "USD: . Temukan lebih banyak wawasan pada\nvolume trading\n\nBitcoin\n\n"
    "(\n\nBTC: ) dalam 24 jam adalah\nHarga\n\nBitcoin\n\ntelah naik sebesar: 0,25\n"
    "Bitcoin\n\nmengalami penurunan sebesar: -29,54"
)

COINDESK_STATBOX_EXCERPT = (
    "Statistik Utama Kapitalisasi Pasar $1.57T Turun 1,35 persen 1,35% Volume "
    "(24j) $11.08B Nilai Terdilusi Penuh $1.65T Vol/Kap. Pasar (24j) 0,70% Total "
    "Pasokan 20.08M BTC Pasokan Maksimum 21.00M BTC Pasokan Beredar 20.08M BTC "
    "Tanggal Peluncuran 2009-01-03 Nomor Blok 966,030 Hadiah Blok 3,13 Ukuran "
    "Blok Terakhir 1,507,904 Jaringan H/s 868884085.20T"
)

CASES = [
    ("1_exact_bug_repro_single_newline", "78347", "78.347\nUSD", ACCEPT_CONTEXTUAL),
    ("2_double_newline_must_not_leak", "78347", "78.347\n\nUSD", {UNRESOLVED, REJECT_CONTEXTUAL}),
    ("3_label_single_newline", "78347", "Price: 78.347\nUSD", ACCEPT_CONTEXTUAL),
    ("4_double_newline_unrelated_section", "78347",
     "Price: 78.347\n\nMarket data\nUSD: unrelated", {UNRESOLVED, REJECT_CONTEXTUAL}),
    ("5_currency_before_token", "78347", "USD 78.347", ACCEPT_CONTEXTUAL),
    ("6_currency_after_token_space_regression", "78347", "78.347 USD",
     ACCEPT_CONTEXTUAL),  # must keep working -- this is the ORIGINAL already-passing shape
    ("7_bare_ambiguous_no_context", "1234", "Value: 1.234", UNRESOLVED),
    ("8_example_scoped_must_still_reject", "1234", "Example price: 1.234 USD", REJECT_CONTEXTUAL),
    ("9_adv_currency_far_away_unrelated", "1234",
     "Total revenue this year was reported at $500,000. In an unrelated note, "
     "the counter shows: 1,234 units in stock.", UNRESOLVED),
    ("10_adv_conflicting_precedent_far", "1234",
     "Change: -1,31 percent. Unrelated value: 1,234 here.", UNRESOLVED),
    ("11_REAL_current_price_usd_full_tradingview", "78347", TRADINGVIEW_FULL_EXCERPT_REAL,
     ACCEPT_CONTEXTUAL),
    ("12_REAL_block_number_rule2_regression", "966030", COINDESK_STATBOX_EXCERPT,
     ACCEPT_CONTEXTUAL),  # Rule 2, must be unaffected by any Rule-1 clause variant
]


def main():
    header = f"{'case':45s} {'BASELINE':10s} {'A':10s} {'B':10s} {'C':10s} expected"
    print(header)
    print("-" * len(header))
    for label, value, source, expected in CASES:
        row = {}
        for name, fn in _RULE1_VARIANTS.items():
            row[name] = resolve_ambiguous_variant(value, source, fn)

        def fmt(v):
            short = {ACCEPT_CONTEXTUAL: "ACCEPT", REJECT_CONTEXTUAL: "REJECT", UNRESOLVED: "UNRES."}
            return short[v]

        def ok(v):
            if isinstance(expected, set):
                return v in expected
            return v == expected

        marks = "".join("Y" if ok(row[n]) else "N" for n in ("BASELINE", "A", "B", "C"))
        exp_label = "/".join(sorted(e.replace("_CONTEXTUAL", "") for e in expected)) if isinstance(expected, set) else expected.replace("_CONTEXTUAL", "")
        print(f"{label:45s} {fmt(row['BASELINE']):10s} {fmt(row['A']):10s} {fmt(row['B']):10s} {fmt(row['C']):10s} {exp_label} [{marks}]")


if __name__ == "__main__":
    main()

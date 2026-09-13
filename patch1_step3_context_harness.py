"""
PATCH1 numeric-fidelity gate -- Step 3: contextual disambiguation harness.

Input contract (agreed 2026-09-08): ONLY facts Step 2 classified as
AMBIGUOUS, plus the raw source_content around the candidate number.
Output: ACCEPT_CONTEXTUAL / REJECT_CONTEXTUAL / UNRESOLVED.

Principle: context may PROVE an interpretation; context may never
INVENT a value. No field_id, no internal variable names, no "this
number is plausible for BTC" reasoning, no LLM guessing.

Two general (non-domain-specific) signals used, in this priority order:
  0. PATCH2 example-scope override -- imported as the PROVEN-CORRECT
     CANDIDATE fix from patch2_example_scope_audit.py (2026-09-08:
     verified 7/7 against the real production _value_is_example_scoped,
     which has a confirmed directional blind spot -- see that script),
     not the real production function directly. If the ambiguous number
     sits in an illustrative "Example: ..." clause -- marker before OR
     after the value -- REJECT_CONTEXTUAL regardless of any other
     signal. PATCH2's intent stays in force -- Step 3 does not
     resurrect example-scoped values.
  1. Currency/unit adjacency: a currency marker (USD, $, Rp, IDR, EUR,
     GBP, USDT, USDC) in the SAME CLAUSE as the ambiguous token implies
     standard 2-decimal money notation -- a 3-digit fractional reading
     is inconsistent with that convention for ANY currency, not just
     BTC -- so the thousands reading is the only one consistent with
     money notation in general.
  2. Document-consistency propagation: if the SAME separator character
     is used UNAMBIGUOUSLY (per Step 2's own multi-group / mixed-type /
     non-3-digit-fraction rules) elsewhere WITHIN A BOUNDED WINDOW of
     the ambiguous token, that resolved role (thousands vs decimal) is
     propagated to the ambiguous token. Window size is a real open
     design question -- see WINDOW_CHARS below and the flagged cases.

If neither signal fires for a given occurrence: UNRESOLVED (no context
proof either way -- NOT invented, NOT guessed).

Depends on Step 2 (patch1_step2_classifier_harness.py) for the numeric
classifier internals, and on the CANDIDATE fix from the PATCH2 audit
(patch2_example_scope_audit.py) for the Rule-0 override -- both must be
in the same directory.

Run from the exact same cwd the uvicorn process uses (patch2_example_scope_audit.py
itself still needs the real fact_checker.py to resolve its own OLD import):
    cd ~/research-assistant
    python3 patch1_step3_context_harness.py
"""
import re
import sys

sys.path.insert(0, ".")

from patch1_step2_classifier_harness import (
    _SOURCE_TOKEN_PATTERN,
    _classify_source_token,
    _parse_candidate_number,
)
# UPDATED 2026-09-08: use the PROVEN-CORRECT CANDIDATE fix from the
# isolated PATCH2 audit (patch2_example_scope_audit.py), not the real
# production OLD _value_is_example_scoped -- OLD has a confirmed
# directional blind spot (misses an example marker that follows a
# decimal-valued fact in the same clause), verified 7/7 fixed by
# CANDIDATE with zero regressions. Production fact_checker.py itself is
# still untouched; this only changes which (already-audited) function
# Step 3's own Rule-0 override calls.
from patch2_example_scope_audit import CANDIDATE as example_scoped


ACCEPT_CONTEXTUAL = "ACCEPT_CONTEXTUAL"
REJECT_CONTEXTUAL = "REJECT_CONTEXTUAL"
UNRESOLVED = "UNRESOLVED"

WINDOW_CHARS = 300  # <-- open design question, see harness output

_CURRENCY_MARKERS = re.compile(
    r'\bUSD\b|\bUSDT\b|\bUSDC\b|\bIDR\b|\bRp\b|\bEUR\b|\bGBP\b|\$',
    re.IGNORECASE,
)

_CLAUSE_BOUNDARY_CHARS = ('.', '!', '?', '\n', ';')


def _clause_span(source_content: str, token_start: int, token_end: int):
    """Same clause-boundary rule as PATCH2's _value_is_example_scoped
    (bounded by '.', '!', '?', newline, ';'), but BUGFIX (2026-09-08,
    found via live Step 3 run): the END boundary must be searched
    starting from token_end (right AFTER the matched numeric token), not
    token_start -- otherwise a token like "78.347" or "1.234" collides
    with its OWN internal '.' and the "clause" gets truncated to just
    past the token's own decimal point, before ever reaching real
    sentence punctuation (or an adjacent unit/currency marker) that
    follows it. Only affects '.'-separated ambiguous tokens; ','-based
    tokens (e.g. "966,030") were never affected since ',' is not in
    _CLAUSE_BOUNDARY_CHARS."""
    start = max(
        (source_content.rfind(c, 0, token_start) for c in _CLAUSE_BOUNDARY_CHARS),
        default=-1,
    )
    end_candidates = [
        p for p in (source_content.find(c, token_end) for c in _CLAUSE_BOUNDARY_CHARS)
        if p != -1
    ]
    end = min(end_candidates) if end_candidates else len(source_content)
    return start + 1, end + 1


def _find_ambiguous_occurrences(candidate_value: str, source_content: str):
    """Locate every source token whose ambiguous (thousands, decimal)
    reading pair contains a value matching the candidate. Returns a list
    of (match_start, match_end, token_text) spans."""
    cand_f = _parse_candidate_number(candidate_value)
    if cand_f is None:
        return []
    spans = []
    for m in _SOURCE_TOKEN_PATTERN.finditer(source_content):
        readings = _classify_source_token(m.group())
        if len(readings) == 2 and any(abs(r - cand_f) < 1e-9 for r in readings):
            spans.append((m.start(), m.end(), m.group()))
    return spans


def _rule1_currency_adjacency(source_content: str, match_start: int, match_end: int) -> bool:
    clause_start, clause_end = _clause_span(source_content, match_start, match_end)
    clause = source_content[clause_start:clause_end]
    return bool(_CURRENCY_MARKERS.search(clause))


def _rule2_document_consistency(source_content: str, match_start: int, match_end: int, token_text: str, cand_f: float, window_chars: int = WINDOW_CHARS) -> bool:
    sep_match = re.search(r'[.,]', token_text)
    if not sep_match:
        return False
    sep_char = sep_match.group()

    win_start = max(0, match_start - window_chars)
    win_end = min(len(source_content), match_end + window_chars)
    window = source_content[win_start:win_end]

    for m in _SOURCE_TOKEN_PATTERN.finditer(window):
        if m.group() == token_text and (win_start + m.start()) == match_start:
            continue  # don't use the token itself as its own precedent
        if sep_char not in m.group():
            continue
        readings = _classify_source_token(m.group())
        if len(readings) != 1:
            continue  # precedent must itself be UNAMBIGUOUS
        # This precedent is unambiguous (len(readings) == 1, checked
        # above). Determine what ROLE the separator plays here (thousands
        # vs decimal) by comparing its single resolved reading to a
        # "thousands" parse of its own digit groups.
        g = re.split(r'[.,]', m.group())
        try:
            thousands_try = float("".join(g))
        except ValueError:
            thousands_try = None
        role_is_thousands = (
            thousands_try is not None and abs(thousands_try - readings[0]) < 1e-9
        )

        our_groups = re.split(r'[.,]', token_text)
        if role_is_thousands:
            candidate_reading = float("".join(our_groups))
        else:
            candidate_reading = float(f"{our_groups[0]}.{our_groups[1]}")

        if abs(candidate_reading - cand_f) < 1e-9:
            return True
    return False


def resolve_ambiguous(candidate_value: str, source_content: str, window_chars: int = WINDOW_CHARS) -> str:
    cand_f = _parse_candidate_number(candidate_value)
    if cand_f is None:
        return UNRESOLVED

    occurrences = _find_ambiguous_occurrences(candidate_value, source_content)
    if not occurrences:
        return UNRESOLVED

    saw_accept = False
    for match_start, match_end, token_text in occurrences:
        clause_start, clause_end = _clause_span(source_content, match_start, match_end)
        clause = source_content[clause_start:clause_end]

        # Rule 0: PATCH2 example-scope override -- highest priority.
        if example_scoped(token_text, clause) or example_scoped(candidate_value, clause):
            return REJECT_CONTEXTUAL

        if _rule1_currency_adjacency(source_content, match_start, match_end):
            saw_accept = True
            continue

        if _rule2_document_consistency(source_content, match_start, match_end, token_text, cand_f, window_chars):
            saw_accept = True
            continue

    return ACCEPT_CONTEXTUAL if saw_accept else UNRESOLVED


# ---------------------------------------------------------------------
# TEST MATRIX A: the 8 cases from the 2026-09-08 Step 3 contract,
# tested EXACTLY as the isolated single-line snippets given -- some are
# expected to come back UNRESOLVED here even though the REAL full-page
# trace resolves them (see Matrix B), because an isolated snippet lacks
# the same-page corroborating numbers Rule 2 needs. Flagged inline.
# ---------------------------------------------------------------------
CASES_A = [
    ("CASE1_price_usd_label",
     "78347", "Bitcoin Price: 78.347 USD", ACCEPT_CONTEXTUAL, "Rule 1 (currency adjacency)"),
    ("CASE2_block_number_isolated",
     "966030", "Nomor Blok: 966,030", UNRESOLVED,
     "No currency here; no OTHER number in this isolated snippet for Rule 2 to use -- "
     "expected UNRESOLVED in isolation even though real full-page context resolves it (see Matrix B)."),
    ("CASE3_value_bare",
     "1234", "Value: 1.234", UNRESOLVED, "no signal at all"),
    ("CASE4_value_with_usd",
     "1234", "Value: 1.234 USD", ACCEPT_CONTEXTUAL,
     "OPEN QUESTION per user: is USD-adjacency alone enough proof? This IS Rule 1 firing -- "
     "confirm you actually want this to ACCEPT."),
    ("CASE5_price_bare",
     "1234", "Price: 1.234", UNRESOLVED, "label word alone is not a signal in this design"),
    # CASE6 (mixed separator "1.234,56") is NOT ambiguous per Step 2 at all
    # (resolves UNAMBIGUOUS_NORMALIZED there already) -- included here only
    # to confirm Step 3 does not mis-handle it if fed in by mistake.
    ("CASE6_mixed_sep_not_really_ambiguous",
     "1234.56", "Price: 1.234,56 USD", UNRESOLVED,
     "Not actually AMBIGUOUS at Step 2 -- would never reach Step 3 in production. "
     "UNRESOLVED here just means 'no ambiguous occurrence found to resolve', which is correct: "
     "Step 2 already accepted it, Step 3 has nothing to do."),
    # CASE7 (wrong value 966031 vs source 966,030) is MISMATCH at Step 2,
    # never reaches Step 3 either -- included defensively.
    ("CASE7_wrong_value_not_really_ambiguous",
     "966031", "Block Number: 966,030", UNRESOLVED,
     "Neither reading of 966,030 equals 966031 -- Step 2 would classify this MISMATCH, "
     "never handing it to Step 3. UNRESOLVED here (no matching occurrence found) is the "
     "harness's honest 'nothing to resolve', not a real REJECT_CONTEXTUAL signal."),
    ("CASE_example_scope_override",
     "1234", "Example price: 1.234 USD", REJECT_CONTEXTUAL,
     "PATCH2 must override Rule 1 even though USD is adjacent."),
]

# ---------------------------------------------------------------------
# TEST MATRIX B: the two REAL ambiguous BTC facts, using actual (abridged
# but verbatim) excerpts from trace 01f3a9ee80d71aafc971ec5b6543daa8.
# ---------------------------------------------------------------------
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

CASES_B = [
    ("REAL_current_price_usd_tradingview",
     "78347", TRADINGVIEW_EXCERPT, "should ACCEPT via Rule 1 (USD right after 78.347)"),
    ("REAL_block_number_coindesk_statbox",
     "966030", COINDESK_STATBOX_EXCERPT,
     "should ACCEPT via Rule 2 ONLY (no currency near 'Nomor Blok'; needs "
     "'1,507,904' precedent within WINDOW_CHARS to resolve -- sensitive to window size)"),
]

# ---------------------------------------------------------------------
# ADVERSARIAL cases: probe the Rule 2 windowing risk directly.
# ---------------------------------------------------------------------
ADVERSARIAL_CASES = [
    ("ADV_conflicting_precedent_far",
     "1234",
     # comma-as-DECIMAL precedent is close (should NOT be used as thousands
     # precedent since it's unambiguous the OTHER way); no thousands
     # precedent anywhere -> must NOT accept via Rule 2.
     "Change: -1,31 percent. Unrelated value: 1,234 here.",
     "must stay UNRESOLVED -- only precedent nearby (-1,31) is unambiguously "
     "DECIMAL-role, not thousands, so it must not license reading 1,234 as 1234."),
    ("ADV_currency_far_away_unrelated",
     "1234",
     # USD appears, but for a DIFFERENT number, far outside the ambiguous
     # token's own clause -> Rule 1 must NOT fire (clause-scoped, not
     # whole-document).
     "Total revenue this year was reported at $500,000. In an unrelated note, "
     "the counter shows: 1,234 units in stock.",
     "must stay UNRESOLVED -- USD is in a different clause; Rule 1 is clause-scoped only."),
]


WINDOW_SWEEP = [50, 100, 200, 300, 500]

# Cases worth sweeping: window size can only affect Rule 2 outcomes.
# Rule-1-only cases (currency adjacency) and Rule-0 (example-scope) are
# window-independent by construction -- included anyway as a sanity
# check that they really don't move.
SWEEP_CASES = [
    ("CASE2_block_number_isolated (no Rule-2 precedent in this 1-line snippet)",
     "966030", "Nomor Blok: 966,030"),
    ("REAL_block_number_coindesk_statbox (Rule-2 target: 1,507,904)",
     "966030", COINDESK_STATBOX_EXCERPT),
    ("REAL_current_price_usd_tradingview (Rule-1 only, should be window-independent)",
     "78347", TRADINGVIEW_EXCERPT),
    ("ADV_conflicting_precedent_far (must stay UNRESOLVED at every window)",
     "1234", "Change: -1,31 percent. Unrelated value: 1,234 here."),
    ("ADV_currency_far_away_unrelated (Rule 1 must not leak across clause; window-independent)",
     "1234", "Total revenue this year was reported at $500,000. In an unrelated note, the counter shows: 1,234 units in stock."),
]


def run_window_sweep():
    print("=" * 100)
    print(f"MATRIX C: window sensitivity sweep {WINDOW_SWEEP}")
    print("=" * 100)
    header = f"{'case':70s} " + " ".join(f"w={w:<4d}" for w in WINDOW_SWEEP)
    print(header)
    for label, value, source in SWEEP_CASES:
        row_results = [resolve_ambiguous(value, source, window_chars=w) for w in WINDOW_SWEEP]
        short = {ACCEPT_CONTEXTUAL: "ACCEPT", REJECT_CONTEXTUAL: "REJECT", UNRESOLVED: "UNRES."}
        row = f"{label:70s} " + " ".join(f"{short[r]:6s}" for r in row_results)
        print(row)
        changed = len(set(row_results)) > 1
        if changed:
            print(f"    ^ SENSITIVE TO WINDOW SIZE -- result changes across the sweep, needs a decision")
    print()


def run(title, cases, tagged=True):
    print("=" * 100)
    print(title)
    print("=" * 100)
    for row in cases:
        if tagged:
            label, value, source, expected, note = row
            result = resolve_ambiguous(value, source)
            mark = "ok" if result == expected else f"MISMATCH-vs-expected(exp={expected})"
            print(f"{label:38s} {value:10s} -> {result:18s} {mark}")
            print(f"    note: {note}")
        else:
            label, value, source, note = row
            result = resolve_ambiguous(value, source)
            print(f"{label:38s} {value:10s} -> {result}")
            print(f"    note: {note}")
    print()


# NOTE (2026-09-08): the old run_patch2_latent_bug_probe() diagnostic
# that lived here has been superseded by the dedicated, more thorough
# patch2_example_scope_audit.py (OLD-vs-CANDIDATE, 7-case matrix,
# includes regression-safety and semicolon-boundary cases). This file
# now consumes that audit's proven-correct CANDIDATE directly (see the
# `example_scoped` import above) instead of re-probing the bug itself.


if __name__ == "__main__":
    print(f"WINDOW_CHARS (default used in Matrix A/B/Adversarial below) = {WINDOW_CHARS}\n")
    run("MATRIX A: isolated single-line snippets (as literally specified 2026-09-08)", CASES_A)
    run("MATRIX B: real trace excerpts (current_price_usd, block_number)", CASES_B, tagged=False)
    run("ADVERSARIAL: probing Rule 1/Rule 2 scoping risk", ADVERSARIAL_CASES, tagged=False)
    run_window_sweep()

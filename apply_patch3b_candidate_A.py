"""
PATCH 3B (2026-09-08): applies to hermes_agent/fact_checker.py, on top
of the already-applied PATCH 3.

What this does (candidate A only, verified via isolated A/B/C matrix +
byte-exact real-trace replay before being wired in):
  1. Replaces _clause_span's boundary detection: '.', '!', '?', ';'
     stay hard boundaries; a bare single '\\n' is now treated as
     layout-only whitespace (NOT a boundary by itself -- e.g. a scraper
     line break between a number and its immediately adjacent unit,
     "78.347\\nUSD"); a blank-line run ('\\n' + optional spaces/tabs +
     '\\n') remains a hard boundary. _clause_span is used only by
     _rule1_currency_adjacency now (see #2).
  2. Decouples PATCH 2's example-scope check (Rule 0) inside
     resolve_ambiguous() from Step 3's clause computation entirely --
     it now calls _value_is_example_scoped() directly against the FULL
     source_content, not a Step-3-sliced clause. _value_is_example_scoped
     itself is NOT touched by this patch; only what resolve_ambiguous()
     passes to it changes, which is what makes Rule 0 provably immune
     to whichever clause-boundary rule Rule 1 uses.

Does NOT touch: _value_is_example_scoped's own internals, Step 2
(classify_value_support and friends), Rule 2 (_rule2_document_consistency,
which uses a raw character window, not a clause, and was confirmed
unaffected in the A/B/C matrix), FactRanker, dedup, evaluate(), or
search/fetch components.

Usage:
    cd ~/research-assistant
    python3 apply_patch3b_candidate_A.py

Same safety pattern as PATCH 3: timestamped backup, assert exact-match
per changed block, write, py_compile, automatic rollback on failure.
This script does NOT run the regression suite -- run
btc_trace_replay.py afterward and confirm 41/41 (in particular
current_price_usd AND price_usd_coindesk both present) before calling
this VERIFIED.
"""
import py_compile
import shutil
import sys
from datetime import datetime

TARGET = "hermes_agent/fact_checker.py"

OLD_BLOCK_1 = '''_CLAUSE_BOUNDARY_CHARS = ('.', '!', '?', '\\n', ';')

_CURRENCY_MARKERS = re.compile(
    r'\\bUSD\\b|\\bUSDT\\b|\\bUSDC\\b|\\bIDR\\b|\\bRp\\b|\\bEUR\\b|\\bGBP\\b|\\$',
    re.IGNORECASE,
)


def _clause_span(source_content: str, token_start: int, token_end: int):
    """Clause boundaries: '.', '!', '?', newline, ';' -- same convention
    as _value_is_example_scoped. The END boundary is searched starting
    from token_end (right after the matched token), not token_start, so
    a token's own internal separator (e.g. the '.' in "78.347") is never
    mistaken for the end of the clause."""
    start = max(
        (source_content.rfind(c, 0, token_start) for c in _CLAUSE_BOUNDARY_CHARS),
        default=-1,
    )
    end_candidates = [
        p for p in (source_content.find(c, token_end) for c in _CLAUSE_BOUNDARY_CHARS)
        if p != -1
    ]
    end = min(end_candidates) if end_candidates else len(source_content)
    return start + 1, end + 1'''

NEW_BLOCK_1 = '''_HARD_BOUNDARY_PATTERN = re.compile(r'[.!?;]|\\n[ \\t]*\\n')

_CURRENCY_MARKERS = re.compile(
    r'\\bUSD\\b|\\bUSDT\\b|\\bUSDC\\b|\\bIDR\\b|\\bRp\\b|\\bEUR\\b|\\bGBP\\b|\\$',
    re.IGNORECASE,
)


def _clause_span(source_content: str, token_start: int, token_end: int):
    """Clause boundaries (PATCH 3B, 2026-09-08): '.', '!', '?', ';', or
    a blank-line run ('\\n' plus optional spaces/tabs plus '\\n') are
    HARD boundaries. A single bare '\\n' is layout-only whitespace (e.g.
    a scraper line break between a number and its immediately adjacent
    unit, such as TradingView's "78.347\\nUSD") and is NOT a boundary by
    itself -- only a genuine blank-line run ends the clause. Verified
    via an isolated A/B/C candidate comparison (12-case matrix,
    including adversarial leak probes) plus a byte-exact replay against
    the real TradingView/CoinDesk evidence before being wired in here;
    this was the only candidate to pass every case.

    The END boundary is searched starting from token_end (right after
    the matched token), not token_start, so a token's own internal
    separator (e.g. the '.' in "78.347") is never mistaken for a clause
    boundary (PATCH 3 behavior, unchanged by this patch)."""
    clause_start = 0
    for m in _HARD_BOUNDARY_PATTERN.finditer(source_content):
        if m.start() >= token_start:
            break
        clause_start = m.end()

    m2 = _HARD_BOUNDARY_PATTERN.search(source_content, token_end)
    clause_end = m2.start() if m2 else len(source_content)

    return clause_start, clause_end'''

OLD_BLOCK_2 = '''    saw_accept = False
    for match_start, match_end, token_text in occurrences:
        clause_start, clause_end = _clause_span(source_content, match_start, match_end)
        clause = source_content[clause_start:clause_end]

        if _value_is_example_scoped(token_text, clause) or _value_is_example_scoped(candidate_value, clause):
            return REJECT_CONTEXTUAL

        if _rule1_currency_adjacency(source_content, match_start, match_end):
            saw_accept = True
            continue

        if _rule2_document_consistency(source_content, match_start, match_end, token_text, cand_f, window_chars):
            saw_accept = True
            continue

    return ACCEPT_CONTEXTUAL if saw_accept else UNRESOLVED'''

NEW_BLOCK_2 = '''    saw_accept = False
    for match_start, match_end, token_text in occurrences:
        # PATCH 3B: PATCH 2's example-scope check (Rule 0) now runs
        # against the FULL source_content, not a Step-3-computed clause
        # -- this decouples it completely from whichever clause-
        # boundary rule Rule 1 uses below. _value_is_example_scoped's
        # own internal boundary logic is untouched by this patch.
        if _value_is_example_scoped(token_text, source_content) or _value_is_example_scoped(candidate_value, source_content):
            return REJECT_CONTEXTUAL

        if _rule1_currency_adjacency(source_content, match_start, match_end):
            saw_accept = True
            continue

        if _rule2_document_consistency(source_content, match_start, match_end, token_text, cand_f, window_chars):
            saw_accept = True
            continue

    return ACCEPT_CONTEXTUAL if saw_accept else UNRESOLVED'''


def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    assert src.count(OLD_BLOCK_1) == 1, (
        f"OLD_BLOCK_1 not found exactly once (found {src.count(OLD_BLOCK_1)}) -- "
        "source has drifted from what PATCH 3 applied, aborting without changes."
    )
    assert src.count(OLD_BLOCK_2) == 1, (
        f"OLD_BLOCK_2 not found exactly once (found {src.count(OLD_BLOCK_2)}) -- "
        "source has drifted from what PATCH 3 applied, aborting without changes."
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{TARGET}.bak_patch3b_candidateA_{timestamp}"
    shutil.copy2(TARGET, backup_path)
    print(f"[backup] {backup_path}")

    new_src = src.replace(OLD_BLOCK_1, NEW_BLOCK_1, 1)
    new_src = new_src.replace(OLD_BLOCK_2, NEW_BLOCK_2, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(new_src)
    print(f"[written] {TARGET}")

    try:
        py_compile.compile(TARGET, doraise=True)
        print("[py_compile] OK")
    except py_compile.PyCompileError as e:
        print(f"[py_compile] FAILED: {e}")
        shutil.copy2(backup_path, TARGET)
        print(f"[rollback] restored {TARGET} from {backup_path}")
        sys.exit(1)

    print()
    print("PATCH 3B applied and compiles. NOT YET VERIFIED.")
    print("Next: restart the service if needed, then run btc_trace_replay.py")
    print("and confirm 41/41 (current_price_usd AND price_usd_coindesk both")
    print("present), and check server log [FACT REJECT] lines for anything")
    print("unexpected before calling this VERIFIED.")


if __name__ == "__main__":
    main()

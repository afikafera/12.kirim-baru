"""
PATCH2 example-scope gate -- isolated audit of the directional blind spot
found 2026-09-08 while building the Step 3 contextual-disambiguation
harness (see project memory "9router search/evidence-loss audit").

This is a SEPARATE bug/thread from the PATCH1 locale-fidelity work.
Nothing here is wired into Step 3 or into production. This script only:
  1. Imports the REAL, currently-deployed _value_is_example_scoped (OLD)
     from hermes_agent/fact_checker.py.
  2. Defines a CANDIDATE with exactly one change: the end-of-clause
     search starts at idx + len(matched_text) instead of idx, so it
     can't collide with a '.' that is PART of the value itself (e.g.
     the decimal point in "1.5 cf").
  3. Runs both against a matrix covering: the known-good baseline
     pattern (marker before value), the proven bug (marker after value,
     same clause), a scope-clarifying control (integer value, no
     internal separator -- must already work in OLD, proving the bug is
     specific to decimal-point collision), a regression-safety case
     (marker in the genuinely NEXT clause -- CANDIDATE must NOT leak
     into it), a semicolon-boundary case, and a documented pre-existing
     limitation (value appears more than once in source) that this fix
     does not attempt to address.

Run from the exact same cwd the uvicorn process uses:
    cd ~/research-assistant
    python3 patch2_example_scope_audit.py
"""
import re
import sys

sys.path.insert(0, ".")

from hermes_agent.fact_checker import (
    _value_is_example_scoped as OLD,
    _NUM_PATTERN,
    _EXAMPLE_MARKERS,
)


def CANDIDATE(value: str, source_content: str) -> bool:
    """Same as production _value_is_example_scoped, with exactly one
    change: the end-of-clause boundary search starts AFTER the matched
    text (idx + match_len), not at its start (idx). This prevents a '.'
    that is part of the value itself (e.g. a decimal point) from being
    mistaken for the end of the clause."""
    if not value or not source_content:
        return False

    idx = source_content.find(value)
    match_len = len(value)
    if idx == -1:
        for num in _NUM_PATTERN.findall(value):
            idx = source_content.find(num)
            if idx != -1:
                match_len = len(num)
                break
    if idx == -1:
        return False

    end_search_from = idx + match_len  # <-- the fix

    start = max(
        source_content.rfind('.', 0, idx),
        source_content.rfind('\n', 0, idx),
        source_content.rfind('!', 0, idx),
        source_content.rfind('?', 0, idx),
        source_content.rfind(';', 0, idx),
    )
    end_candidates = [
        p for p in (
            source_content.find('.', end_search_from),
            source_content.find('!', end_search_from),
            source_content.find('?', end_search_from),
            source_content.find(';', end_search_from),
        ) if p != -1
    ]
    end = min(end_candidates) if end_candidates else len(source_content)

    sentence = source_content[start + 1:end + 1]
    return bool(_EXAMPLE_MARKERS.search(sentence))


# ---------------------------------------------------------------------
# Test matrix. Each case: (label, value, source_content, expected,
# purpose). "expected" is what a human reading the source would agree
# is correct -- this is what CANDIDATE must match on every case, while
# OLD is expected to mismatch specifically on the proven-bug case.
# ---------------------------------------------------------------------
CASES = [
    ("marker_before_value",
     "1.5 cf",
     "For example, this measurement of 1.5 cf net is used in the formula.",
     True,
     "PATCH2's originally-tested pattern. Must stay True in both OLD and CANDIDATE."),

    ("marker_after_value_same_clause",
     "1.5 cf",
     "This measurement of 1.5 cf net is just an example for illustration.",
     True,
     "THE PROVEN BUG. OLD is expected to wrongly return False here; "
     "CANDIDATE must return True."),

    ("no_marker_control",
     "1.5 cf",
     "This measurement of 1.5 cf net is the actual product specification.",
     False,
     "No marker anywhere. Must stay False in both."),

    ("integer_value_marker_after_scope_control",
     "78347",
     "The reported count is 78347, for example, in typical usage.",
     True,
     "SCOPE CONTROL: value has NO internal separator, so the bug should "
     "NOT manifest even in OLD -- both OLD and CANDIDATE must return True here. "
     "If OLD fails this one too, the bug is broader than diagnosed."),

    ("regression_marker_in_next_clause",
     "1.5 cf",
     "The value is 1.5 cf. For example, other units use 2.0 cf.",
     False,
     "REGRESSION SAFETY: marker is in the NEXT sentence, a genuinely "
     "different clause. CANDIDATE must NOT leak into it (must stay False, "
     "same as OLD) -- proves the fix doesn't overcorrect into a new false-positive."),

    ("semicolon_boundary",
     "1.5 cf",
     "The measurement is 1.5 cf; for example, other configurations differ.",
     False,
     "Semicolon (PATCH2b) should end the clause right after '1.5 cf', "
     "excluding 'for example' which is on the other side of it. "
     "Must stay False in both OLD and CANDIDATE."),

    ("known_limitation_multi_occurrence_real_then_example",
     "1.5 cf",
     "The product uses 1.5 cf net for the main chamber. "
     "For example, a smaller model might use 1.5 cf net for a secondary chamber.",
     False,
     "KNOWN PRE-EXISTING LIMITATION, not addressed by this fix: "
     ".find(value) only checks the FIRST occurrence. Here the first "
     "occurrence is genuinely NOT example-scoped, so False is correct -- "
     "included to document current (unchanged) behavior, not to claim it's fixed."),
]


def main():
    print(f"{'case':45s} {'OLD':6s} {'CANDIDATE':10s} {'expected':9s} status")
    print("-" * 100)
    old_matches = 0
    cand_matches = 0
    for label, value, source, expected, purpose in CASES:
        old_result = OLD(value, source)
        cand_result = CANDIDATE(value, source)
        old_ok = old_result == expected
        cand_ok = cand_result == expected
        old_matches += old_ok
        cand_matches += cand_ok
        tag = "ok" if (old_ok and cand_ok) else (
            "OLD-BUG-CONFIRMED, CANDIDATE-FIXES-IT" if (not old_ok and cand_ok)
            else "CANDIDATE-REGRESSION (needs investigation)" if not cand_ok
            else "unexpected"
        )
        print(f"{label:45s} {str(old_result):6s} {str(cand_result):10s} {str(expected):9s} {tag}")
        print(f"    purpose: {purpose}")
    print("-" * 100)
    print(f"OLD matches expected:       {old_matches}/{len(CASES)}")
    print(f"CANDIDATE matches expected: {cand_matches}/{len(CASES)}")


if __name__ == "__main__":
    main()

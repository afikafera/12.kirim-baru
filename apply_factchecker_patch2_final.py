"""
APPLY PATCH 2b (semicolon-boundary fix) to hermes_agent/fact_checker.py

Targets production as it ACTUALLY stands right now: PATCH 1 + PATCH 2
(base, no semicolon) already live -- confirmed by reading the file
contents directly. The earlier apply_factchecker_patch2_final.py wrongly
assumed PATCH 2 was not yet applied and aborted safely (0 matches, no
changes written) when that assumption didn't hold.

This is now a small, targeted patch: only the _value_is_example_scoped()
function body changes -- add ';' to both the `start` and `end_candidates`
boundary-character lists, and update the docstring to explain why. The
accept-loop wiring (the `if _value_is_example_scoped(...)` call) is
already live and untouched by this patch.

Proven by verify_factchecker_patch2b_semicolon.py (4/4 cases PASSED):
  - "For example, X; this one specifies 55 Hz" -> 55 Hz now SURVIVES
  - "Example: 4-inch port, 35 Hz tuning, 1.5 cf net." -> still REJECTED
  - period-separated equivalent -> still SURVIVES (non-regression)
  - ordinary non-example facts -> still SURVIVE

No contrastive-conjunction heuristic (but/however/this model) added --
semicolon only, per explicit decision. Does NOT touch search/planner/
synthesis. Does NOT add a second LLM call.

Safety:
  - Timestamped backup before writing anything.
  - Exact-match count == 1 assertion on the changed block; aborts with no
    changes written if the file doesn't match what was just confirmed.
  - py_compile validation, with automatic rollback on failure.

Run ON THE SERVER:
    cd ~/research-assistant
    python3 apply_factchecker_patch2b_semicolon.py
"""
import datetime
import py_compile
import shutil
import sys

TARGET = "hermes_agent/fact_checker.py"


def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{TARGET}.bak_patch2b_{timestamp}"
    shutil.copy2(TARGET, backup_path)
    print(f"[backup] {TARGET} -> {backup_path}")

    old_fn = '''def _value_is_example_scoped(value: str, source_content: str) -> bool:
    """Deterministic example-scope gate (PATCH 2): a fact is rejected if
    its value sits in the same sentence as an example/illustration marker
    in the source content. Values inside an illustrative example (e.g. a
    formula's worked example) are not the subject's actual values, even
    though PATCH 1's numeric fidelity gate correctly lets them through
    (the numbers genuinely appear in the source)."""
    if not value or not source_content:
        return False

    idx = source_content.find(value)
    if idx == -1:
        for num in _NUM_PATTERN.findall(value):
            idx = source_content.find(num)
            if idx != -1:
                break
    if idx == -1:
        return False

    start = max(
        source_content.rfind('.', 0, idx),
        source_content.rfind('\\n', 0, idx),
        source_content.rfind('!', 0, idx),
        source_content.rfind('?', 0, idx),
    )
    end_candidates = [
        p for p in (
            source_content.find('.', idx),
            source_content.find('!', idx),
            source_content.find('?', idx),
        ) if p != -1
    ]
    end = min(end_candidates) if end_candidates else len(source_content)

    sentence = source_content[start + 1:end + 1]
    return bool(_EXAMPLE_MARKERS.search(sentence))'''

    new_fn = '''def _value_is_example_scoped(value: str, source_content: str) -> bool:
    """Deterministic example-scope gate (PATCH 2): a fact is rejected if
    its value sits in the same clause as an example/illustration marker
    in the source content. Values inside an illustrative example (e.g. a
    formula's worked example) are not the subject's actual values, even
    though PATCH 1's numeric fidelity gate correctly lets them through
    (the numbers genuinely appear in the source).

    Clause boundaries are '.', '!', '?', newline, and ';' (PATCH 2b) --
    the semicolon is included so a compound sentence like "For example,
    X; this one specifies Y" does not let the leading example marker
    reach across the semicolon and wrongly reject the genuine value Y.
    No contrastive-conjunction heuristic (but/however/this model) is
    used -- semicolon only, kept deterministic and minimal."""
    if not value or not source_content:
        return False

    idx = source_content.find(value)
    if idx == -1:
        for num in _NUM_PATTERN.findall(value):
            idx = source_content.find(num)
            if idx != -1:
                break
    if idx == -1:
        return False

    start = max(
        source_content.rfind('.', 0, idx),
        source_content.rfind('\\n', 0, idx),
        source_content.rfind('!', 0, idx),
        source_content.rfind('?', 0, idx),
        source_content.rfind(';', 0, idx),
    )
    end_candidates = [
        p for p in (
            source_content.find('.', idx),
            source_content.find('!', idx),
            source_content.find('?', idx),
            source_content.find(';', idx),
        ) if p != -1
    ]
    end = min(end_candidates) if end_candidates else len(source_content)

    sentence = source_content[start + 1:end + 1]
    return bool(_EXAMPLE_MARKERS.search(sentence))'''

    count = src.count(old_fn)
    assert count == 1, f"expected exactly 1 match for _value_is_example_scoped() body, found {count}. Aborting, no changes written."
    src = src.replace(old_fn, new_fn)
    print("[fix] semicolon added to both boundary-character lists in _value_is_example_scoped()")

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"[write] {TARGET} updated")

    try:
        py_compile.compile(TARGET, doraise=True)
        print(f"[py_compile] OK: {TARGET}")
    except py_compile.PyCompileError as e:
        print(f"[py_compile] FAILED: {e}")
        print(f"[rollback] restoring backup {backup_path} -> {TARGET}")
        shutil.copy2(backup_path, TARGET)
        sys.exit(1)

    print("")
    print("PATCH 2b (semicolon boundary) applied successfully.")
    print(f"Backup kept at: {backup_path}")
    print("Next: restart the service, then run production_regression_factchecker_patch1.py")
    print("to confirm no regression, plus a live case resembling")
    print("'for example ... ; ...' if one is available, to confirm the fix behaves live")
    print("the same way it did in the FakeLLM VERIFY.")


if __name__ == "__main__":
    main()

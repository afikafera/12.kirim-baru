"""
APPLY PATCH 2 to hermes_agent/fact_checker.py (requires PATCH 1 already applied)

Adds the example-scope gate proven by verify_factchecker_patch2.py (all
cases PASSED on the server, including the documented false-positive
limitation demonstration):

  _value_is_example_scoped(value, source_content) -- rejects a fact if its
  value sits in the same sentence as an example/illustration marker
  (example, e.g., for instance, sample calculation, misalnya, contoh, ...)
  in the source content. Applied AFTER the existing PATCH 1 numeric
  fidelity gate and BEFORE a fact is added to `validated`. Logs:
    [FACT REJECT] field=<field> reason=example_value_not_actual value=<v> source=<url>

Root case this targets: a source's worked example ("Example: 4-inch port,
35 Hz tuning, 1.5 cf net") describes illustrative values for a FORMULA,
not the actual subject product's (e.g. ACR 12500 Black) real design
values. PATCH 1 correctly lets these through (the numbers ARE in the
source); PATCH 2 correctly rejects them anyway (they are scoped to an
example, not the subject).

Known, accepted limitation (by design, fail-closed over fail-open): a
genuine spec value sharing a sentence with an unrelated use of an example
marker word will also be rejected. Demonstrated and accepted in the
VERIFY run, not silently introduced.

Does NOT touch search/planner/synthesis. Does NOT add a second LLM call.

Safety:
  - Makes a timestamped backup before writing anything.
  - Each old block is matched with an exact string count == 1 assertion;
    if the file has drifted from what was audited (e.g. PATCH 1 not yet
    applied, or applied differently than expected), this aborts with no
    changes written.
  - Runs py_compile on the patched file before declaring success.

Run ON THE SERVER:
    cd ~/research-assistant
    python3 apply_factchecker_patch2.py
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
    backup_path = f"{TARGET}.bak_patch2_{timestamp}"
    shutil.copy2(TARGET, backup_path)
    print(f"[backup] {TARGET} -> {backup_path}")

    # -----------------------------------------------------------------
    # FIX 1: add _EXAMPLE_MARKERS + _value_is_example_scoped() helper
    # -----------------------------------------------------------------
    old_helper = '''def _value_supported_by_source(value: str, source_content: str) -> bool:
    """Deterministic numeric fidelity gate (PATCH 1): every numeric token
    in a candidate fact value must literally appear in the raw content of
    the source it claims to come from. Non-numeric values pass through
    unchanged (semantic/text validation is out of scope for PATCH 1)."""
    numbers = _NUM_PATTERN.findall(value or "")
    if not numbers:
        return True
    haystack = source_content or ""
    return all(num in haystack for num in numbers)


class FactChecker:'''

    new_helper = '''def _value_supported_by_source(value: str, source_content: str) -> bool:
    """Deterministic numeric fidelity gate (PATCH 1): every numeric token
    in a candidate fact value must literally appear in the raw content of
    the source it claims to come from. Non-numeric values pass through
    unchanged (semantic/text validation is out of scope for PATCH 1)."""
    numbers = _NUM_PATTERN.findall(value or "")
    if not numbers:
        return True
    haystack = source_content or ""
    return all(num in haystack for num in numbers)


_EXAMPLE_MARKERS = re.compile(
    r'\\b(example|e\\.g\\.|for instance|for example|sample calculation|'
    r'misalnya|contoh|sebagai contoh)\\b',
    re.IGNORECASE,
)


def _value_is_example_scoped(value: str, source_content: str) -> bool:
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
    return bool(_EXAMPLE_MARKERS.search(sentence))


class FactChecker:'''

    count = src.count(old_helper)
    assert count == 1, f"FIX 1: expected exactly 1 match for _value_supported_by_source block, found {count}. Aborting, no changes written."
    src = src.replace(old_helper, new_helper)
    print("[fix 1] _EXAMPLE_MARKERS + _value_is_example_scoped() helper added")

    # -----------------------------------------------------------------
    # FIX 2: insert the example-scope gate before a fact is accepted
    # -----------------------------------------------------------------
    old_accept = '''                fact_value = str(value.get("value", ""))
                source_content = url_to_content.get(src, "")
                if not _value_supported_by_source(fact_value, source_content):
                    logger.warning(
                        "[FACT REJECT] field=%s reason=value_not_in_evidence value=%r source=%r",
                        key,
                        fact_value,
                        src,
                    )
                    continue

                validated[key] = value'''

    new_accept = '''                fact_value = str(value.get("value", ""))
                source_content = url_to_content.get(src, "")
                if not _value_supported_by_source(fact_value, source_content):
                    logger.warning(
                        "[FACT REJECT] field=%s reason=value_not_in_evidence value=%r source=%r",
                        key,
                        fact_value,
                        src,
                    )
                    continue

                if _value_is_example_scoped(fact_value, source_content):
                    logger.warning(
                        "[FACT REJECT] field=%s reason=example_value_not_actual value=%r source=%r",
                        key,
                        fact_value,
                        src,
                    )
                    continue

                validated[key] = value'''

    count = src.count(old_accept)
    assert count == 1, f"FIX 2: expected exactly 1 match for accept block, found {count}. Aborting, no changes written."
    src = src.replace(old_accept, new_accept)
    print("[fix 2] example-scope gate inserted before fact acceptance")

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
    print("PATCH 2 applied successfully.")
    print(f"Backup kept at: {backup_path}")
    print("Next: restart the service and re-run the production regression")
    print("(subenclosure.net / ACR 12500 Black) to confirm the 35 Hz / 1.5 cf")
    print("example-clause values no longer survive, and non-example facts")
    print("(Fs, material, port type) are unaffected.")


if __name__ == "__main__":
    main()

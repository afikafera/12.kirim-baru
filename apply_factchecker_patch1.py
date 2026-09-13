"""
APPLY PATCH 1 to hermes_agent/fact_checker.py

Applies exactly the two fixes proven by verify_factchecker_patch1.py
(all 4 cases PASSED on the server):

  1. extract_json(): pick the bracket-scoped regex pattern matching
     whichever bracket ('{' or '[') appears FIRST in the text, instead
     of always trying the object pattern first. Fixes the total=0
     silent-drop bug for single-element JSON array responses.

  2. extract_facts_batch(): add a deterministic numeric value/content
     fidelity gate, applied AFTER the existing provenance (URL) guard
     and BEFORE a fact is added to `validated`. Rejects any fact whose
     value contains a number that does not literally appear in the
     content of its cited source. Logs:
       [FACT REJECT] field=<field> reason=value_not_in_evidence value=<v> source=<url>
     Non-numeric values are untouched (out of scope for PATCH 1).

Does NOT touch search/planner/synthesis. Does NOT add a second LLM call.

Safety:
  - Makes a timestamped backup before writing anything.
  - Each old block is matched with an exact string count == 1 assertion;
    if the file has drifted from what was audited, this aborts with no
    changes written.
  - Runs py_compile on the patched file before declaring success.

Run ON THE SERVER:
    cd ~/research-assistant
    python3 apply_factchecker_patch1.py
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
    backup_path = f"{TARGET}.bak_patch1_{timestamp}"
    shutil.copy2(TARGET, backup_path)
    print(f"[backup] {TARGET} -> {backup_path}")

    # -----------------------------------------------------------------
    # FIX 1: extract_json() bracket-order fix
    # -----------------------------------------------------------------
    old_extract_json = '''def extract_json(text: str):
    try:
        return json.loads(text)
    except:
        pass
    for pattern in [r'\\{.*\\}', r'\\[.*\\]']:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return {}'''

    new_extract_json = '''def extract_json(text: str):
    try:
        return json.loads(text)
    except:
        pass
    first_brace = text.find('{')
    first_bracket = text.find('[')
    if first_bracket != -1 and (first_brace == -1 or first_bracket < first_brace):
        patterns = [r'\\[.*\\]', r'\\{.*\\}']
    else:
        patterns = [r'\\{.*\\}', r'\\[.*\\]']
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return {}


_NUM_PATTERN = re.compile(r'\\d+(?:[.,]\\d+)?')


def _value_supported_by_source(value: str, source_content: str) -> bool:
    """Deterministic numeric fidelity gate (PATCH 1): every numeric token
    in a candidate fact value must literally appear in the raw content of
    the source it claims to come from. Non-numeric values pass through
    unchanged (semantic/text validation is out of scope for PATCH 1)."""
    numbers = _NUM_PATTERN.findall(value or "")
    if not numbers:
        return True
    haystack = source_content or ""
    return all(num in haystack for num in numbers)'''

    count = src.count(old_extract_json)
    assert count == 1, f"FIX 1: expected exactly 1 match for extract_json() block, found {count}. Aborting, no changes written."
    src = src.replace(old_extract_json, new_extract_json)
    print("[fix 1] extract_json() bracket-order fix + _value_supported_by_source() helper applied")

    # -----------------------------------------------------------------
    # FIX 2a: build url_to_content map alongside valid_urls
    # -----------------------------------------------------------------
    old_valid_urls = '''            valid_urls = {
                str(e.get("url", "")).strip()
                for e in all_evidence
                if e.get("url")
            }

            validated = {}'''

    new_valid_urls = '''            valid_urls = {
                str(e.get("url", "")).strip()
                for e in all_evidence
                if e.get("url")
            }
            url_to_content = {
                str(e.get("url", "")).strip(): e.get("content", "")
                for e in all_evidence
                if e.get("url")
            }

            validated = {}'''

    count = src.count(old_valid_urls)
    assert count == 1, f"FIX 2a: expected exactly 1 match for valid_urls block, found {count}. Aborting, no changes written."
    src = src.replace(old_valid_urls, new_valid_urls)
    print("[fix 2a] url_to_content map added")

    # -----------------------------------------------------------------
    # FIX 2b: insert the fidelity gate before a fact is accepted
    # -----------------------------------------------------------------
    old_accept = '''                if not src or src not in valid_urls:
                    logger.warning(
                        "[FACT REJECT] field=%s source=%r not in evidence",
                        key,
                        src,
                    )
                    continue

                validated[key] = value'''

    new_accept = '''                if not src or src not in valid_urls:
                    logger.warning(
                        "[FACT REJECT] field=%s source=%r not in evidence",
                        key,
                        src,
                    )
                    continue

                fact_value = str(value.get("value", ""))
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

    count = src.count(old_accept)
    assert count == 1, f"FIX 2b: expected exactly 1 match for accept block, found {count}. Aborting, no changes written."
    src = src.replace(old_accept, new_accept)
    print("[fix 2b] value-fidelity gate inserted before fact acceptance")

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
    print("PATCH 1 applied successfully.")
    print(f"Backup kept at: {backup_path}")
    print("Next: restart the service and re-run the exact production case")
    print("(subenclosure.net / ACR 12500 Black) to confirm regression,")
    print("then check logs for [FACT REJECT] ... reason=value_not_in_evidence")


if __name__ == "__main__":
    main()

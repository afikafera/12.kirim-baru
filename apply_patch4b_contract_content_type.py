"""
PATCH 4b-i (2026-09-08): hermes_agent/llm_output_contract.py -- reject
non-string content as an explicit "invalid_content_type" failure,
instead of silently passing it through as "no failure detected" and
letting the caller's .strip() crash downstream.

Root cause proven live in the PATCH 4 regression run: @cf/qwen/qwen2.5-
coder-32b-instruct returned finish_reason=stop with content as a dict
(not a string). The OLD contract checked `not str(content).strip()`,
which stringifies the dict first (e.g. "{'a': 1}" is truthy) and so
never flagged it -- TaskPlanner then called content.strip() on the raw
dict object and crashed with "'dict' object has no attribute 'strip'",
caught by the outer except and correctly retried, but only by accident
(via a generic exception, not a deliberate contract check).

Does NOT touch TaskPlanner.plan(), does NOT add max_tokens -- that is a
separate, second small patch (PATCH 4b-ii) pending the current
LLMAnalyzer.analyze() signature.

Usage:
    cd ~/research-assistant
    python3 apply_patch4b_contract_content_type.py

Same safety pattern: timestamped backup, assert exact-match, write,
py_compile, automatic rollback on failure.
"""
import py_compile
import shutil
import sys
from datetime import datetime

TARGET = "hermes_agent/llm_output_contract.py"

OLD_BLOCK = '''LLM_FAILURE_EMPTY_CONTENT = "empty_content"
LLM_FAILURE_LENGTH_TRUNCATED = "length_truncated"


def llm_output_failure(result):
    """Classify an LLMAnalyzer.analyze() result against the minimal
    output contract. Returns None when the result has usable content;
    otherwise a short failure-reason string:

    - "empty_content": result is not a dict, or content is None, or an
      empty / whitespace-only string.
    - "length_truncated": finish_reason == "length" -- the provider
      stopped because it hit its own output cap, not because the
      response was actually complete. A non-empty content can still
      carry this reason (a partial response cut mid-output)."""
    if not isinstance(result, dict):
        return LLM_FAILURE_EMPTY_CONTENT
    content = result.get("content")
    if content is None or not str(content).strip():
        return LLM_FAILURE_EMPTY_CONTENT
    if str(result.get("finish_reason", "")).strip().lower() == "length":
        return LLM_FAILURE_LENGTH_TRUNCATED
    return None'''

NEW_BLOCK = '''LLM_FAILURE_EMPTY_CONTENT = "empty_content"
LLM_FAILURE_LENGTH_TRUNCATED = "length_truncated"
LLM_FAILURE_INVALID_CONTENT_TYPE = "invalid_content_type"


def llm_output_failure(result):
    """Classify an LLMAnalyzer.analyze() result against the minimal
    output contract. Returns None when the result has usable content;
    otherwise a short failure-reason string:

    - "empty_content": result is not a dict, or content is None, or an
      empty / whitespace-only string.
    - "invalid_content_type": content is present but not a string (e.g.
      a dict or list) -- PATCH 4b: some providers/models return a
      structured message.content instead of text even with
      finish_reason=stop; checking `str(content).strip()` alone missed
      this (a non-empty dict stringifies truthy), so callers doing
      content.strip() crashed on the raw object instead of getting a
      detected contract failure.
    - "length_truncated": finish_reason == "length" -- the provider
      stopped because it hit its own output cap, not because the
      response was actually complete. A non-empty content can still
      carry this reason (a partial response cut mid-output)."""
    if not isinstance(result, dict):
        return LLM_FAILURE_EMPTY_CONTENT
    content = result.get("content")
    if content is None:
        return LLM_FAILURE_EMPTY_CONTENT
    if not isinstance(content, str):
        return LLM_FAILURE_INVALID_CONTENT_TYPE
    if not content.strip():
        return LLM_FAILURE_EMPTY_CONTENT
    if str(result.get("finish_reason", "")).strip().lower() == "length":
        return LLM_FAILURE_LENGTH_TRUNCATED
    return None'''


def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    assert src.count(OLD_BLOCK) == 1, (
        f"OLD_BLOCK not found exactly once (found {src.count(OLD_BLOCK)}) -- "
        "source has drifted from what PATCH 4 applied, aborting without changes."
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{TARGET}.bak_patch4b_content_type_{timestamp}"
    shutil.copy2(TARGET, backup_path)
    print(f"[backup] {backup_path}")

    new_src = src.replace(OLD_BLOCK, NEW_BLOCK, 1)

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
    print("PATCH 4b-i applied and compiles. NOT YET VERIFIED.")
    print("This only affects the contract classifier -- TaskPlanner.plan() logic is")
    print("unchanged, so a dict-content response will now show")
    print("'[task_planner] output contract failed (attempt N/2): invalid_content_type'")
    print("instead of '[task_planner] parse failed (attempt N/2): 'dict' object has no")
    print("attribute 'strip'' -- same retry behavior, but via a deliberate check now.")


if __name__ == "__main__":
    main()

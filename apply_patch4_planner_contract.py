"""
PATCH 4 (2026-09-08): TaskPlanner output contract + early-failure retry,
before _fallback(). Does NOT touch _fallback() itself, does NOT pass
max_tokens (deferred to the budget-accounting patch), does NOT touch
CompletenessChecker/FactChecker/Synthesis (deferred to later patches
per the agreed sequencing).

What this does:
  1. Creates hermes_agent/llm_output_contract.py -- a small, reusable
     DETECTION-only helper (llm_output_failure()) classifying an
     LLMAnalyzer.analyze() result as usable or as one of two explicit
     failure reasons (empty_content / length_truncated). No retry or
     fallback policy lives in this module -- callers decide.
  2. Rewrites TaskPlanner.plan() to retry (2 attempts total, 1 retry)
     BEFORE calling _fallback(): a retry fires on a call exception, on
     an llm_output_failure() hit, or on a json.loads() failure after
     non-empty content. _fallback() is only reached after every
     attempt is exhausted -- unchanged from today's behavior otherwise.

Usage:
    cd ~/research-assistant
    python3 apply_patch4_planner_contract.py

Same safety pattern as prior patches: timestamped backup of the
modified file, assert exact-match before rewriting, py_compile both
files, automatic rollback of task_planner.py on failure (and removal
of the new contract file if it was just created by this run).

Does NOT run the regression suite. Next steps after this compiles:
production TaskPlanner regression with round-robin live, THEN (only if
that passes) move to Research Budget accounting -- not before.
"""
import os
import py_compile
import shutil
import sys
from datetime import datetime

TARGET = "hermes_agent/task_planner.py"
CONTRACT_FILE = "hermes_agent/llm_output_contract.py"

CONTRACT_MODULE_CONTENT = '''"""Explicit LLM output contract (PATCH 4, 2026-09-08).

Turns a truncated or empty LLM completion into a DETECTABLE failure
signal instead of letting it propagate as a generic exception -- or,
worse, straight through to the user as a null/empty answer (the
synthesis and direct-Q&A call sites in orchestrator.py have no
validation at all today; that is a separate, not-yet-scheduled patch).

Shared so TaskPlanner (first caller, PATCH 4) and later FactChecker /
synthesis call sites can apply the same minimal contract without
duplicating the checks.

This module only DETECTS a failure; it carries no retry or fallback
policy of its own -- each caller decides what to do (retry, fall back,
let the round-robin pick a different model on the next attempt).
"""

LLM_FAILURE_EMPTY_CONTENT = "empty_content"
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
    return None
'''

OLD_IMPORTS = '''import json
import re
import logging

logger = logging.getLogger(__name__)'''

NEW_IMPORTS = '''import json
import re
import logging

from hermes_agent.llm_output_contract import llm_output_failure

logger = logging.getLogger(__name__)'''

OLD_PLAN_BODY = '''        try:
            result = self.llm.analyze(
                "Kamu knowledge planner. Return JSON only.",
                prompt, temperature=0.2
            )
            text = result["content"].strip().replace("```json", "").replace("```", "")
            logger.info("[PLANNER RAW] %r", text)
            plan = json.loads(text)
            plan = normalize_plan_entity_anchor(plan, context)
            return plan
        except Exception as e:
            logger.warning(f"[task_planner] fail: {e}")
            return self._fallback(goal, context)'''

NEW_PLAN_BODY = '''        # PATCH 4: validate/retry BEFORE _fallback() -- a truncated or
        # empty LLM response used to go straight to _fallback(), which
        # sets topic=goal (the full raw user question) as the search
        # query. Retrying first gives the 9router round-robin a chance
        # to land on a model that actually completes the JSON.
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                result = self.llm.analyze(
                    "Kamu knowledge planner. Return JSON only.",
                    prompt, temperature=0.2
                )
            except Exception as e:
                logger.warning(f"[task_planner] call failed (attempt {attempt}/{max_attempts}): {e}")
                continue

            failure = llm_output_failure(result)
            if failure is not None:
                logger.warning(f"[task_planner] output contract failed (attempt {attempt}/{max_attempts}): {failure}")
                continue

            try:
                text = result["content"].strip().replace("```json", "").replace("```", "")
                logger.info("[PLANNER RAW] %r", text)
                plan = json.loads(text)
                plan = normalize_plan_entity_anchor(plan, context)
                return plan
            except Exception as e:
                logger.warning(f"[task_planner] parse failed (attempt {attempt}/{max_attempts}): {e}")
                continue

        logger.warning(f"[task_planner] all {max_attempts} attempts exhausted, falling back")
        return self._fallback(goal, context)'''


def main():
    contract_created = False

    if os.path.exists(CONTRACT_FILE):
        print(f"[abort] {CONTRACT_FILE} already exists -- not overwriting. "
              "Inspect it manually before re-running.")
        sys.exit(1)

    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    assert src.count(OLD_IMPORTS) == 1, (
        f"OLD_IMPORTS not found exactly once (found {src.count(OLD_IMPORTS)}) -- "
        "source has drifted, aborting without changes."
    )
    assert src.count(OLD_PLAN_BODY) == 1, (
        f"OLD_PLAN_BODY not found exactly once (found {src.count(OLD_PLAN_BODY)}) -- "
        "source has drifted, aborting without changes."
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{TARGET}.bak_patch4_planner_contract_{timestamp}"
    shutil.copy2(TARGET, backup_path)
    print(f"[backup] {backup_path}")

    new_src = src.replace(OLD_IMPORTS, NEW_IMPORTS, 1)
    new_src = new_src.replace(OLD_PLAN_BODY, NEW_PLAN_BODY, 1)

    try:
        with open(CONTRACT_FILE, "w", encoding="utf-8") as f:
            f.write(CONTRACT_MODULE_CONTENT)
        contract_created = True
        print(f"[written] {CONTRACT_FILE}")

        with open(TARGET, "w", encoding="utf-8") as f:
            f.write(new_src)
        print(f"[written] {TARGET}")

        py_compile.compile(CONTRACT_FILE, doraise=True)
        print(f"[py_compile] {CONTRACT_FILE} OK")
        py_compile.compile(TARGET, doraise=True)
        print(f"[py_compile] {TARGET} OK")

    except Exception as e:
        print(f"[FAILED] {e}")
        shutil.copy2(backup_path, TARGET)
        print(f"[rollback] restored {TARGET} from {backup_path}")
        if contract_created and os.path.exists(CONTRACT_FILE):
            os.remove(CONTRACT_FILE)
            print(f"[rollback] removed {CONTRACT_FILE}")
        sys.exit(1)

    print()
    print("PATCH 4 applied and compiles. NOT YET VERIFIED.")
    print("Next: production TaskPlanner regression with round-robin live")
    print("(watch for [task_planner] log lines showing retry attempts),")
    print("THEN a real BTC-style trace replay, before touching")
    print("CompletenessChecker/FactChecker/Synthesis or Research Budget.")


if __name__ == "__main__":
    main()

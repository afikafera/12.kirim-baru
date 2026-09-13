"""
PATCH 5 (2026-09-08): hermes_agent/fact_checker.py -- adaptive output
budget + retry-before-give-up for extract_facts_batch()'s LLM call,
mirroring PATCH 4/4c's TaskPlanner pattern and reusing the same
llm_output_failure() contract.

Root cause proven live in trace 28be48030145e6762e3eb55ac235d805:
FactChecker's extraction call never passes max_tokens, hit the provider
default of 256 tokens, and got cut off mid-JSON ("market_context_index_
change": {"value": "-  <EOF>) -- extract_json()'s regex fallback then
returns {} because the outer object is never closed, even though the
model HAD already produced bitcoin_price: "78,533.76 USDT" before being
cut off. A second attempt (the orchestrator's own per-node retry in a
later iteration) reproduced the identical failure because nothing about
the request changed between attempts.

Retry fires ONLY on: the call raising an exception, or
llm_output_failure(result) detecting empty_content / invalid_content_type
/ length_truncated. It does NOT fire just because extract_json() itself
returns {} on an otherwise-clean response -- an evidence page can
legitimately contain no extractable facts (extractor rule 8), and that
must stay a valid, non-retried outcome.

Schedule (1024, then 2048 tokens) is the user's own earlier example
figure for this specific caller -- larger than TaskPlanner's 512/1024
because extraction payloads (multiple evidence sources bundled into one
call) are typically bigger. Not claimed final; the next regression
measures whether it's enough for this trace's ~7-fact case, and whether
much larger multi-source extractions (BTC trace with 41 facts) still
need more headroom -- deferred to a later measurement.

Does NOT touch the validation pipeline after extraction (provenance
guard, PATCH1/2, Step2/Step3, dedup), does NOT touch Synthesis (that is
the next, separate patch per the user's sequencing), does NOT touch
TaskPlanner/CompletenessChecker.

Usage:
    cd ~/research-assistant
    python3 apply_patch5_factchecker_budget.py

Same safety pattern: timestamped backup, assert exact-match, write,
py_compile, automatic rollback on failure.
"""
import py_compile
import shutil
import sys
from datetime import datetime

TARGET = "hermes_agent/fact_checker.py"

OLD_IMPORTS = '''import json
import re
import logging
from collections import Counter'''

NEW_IMPORTS = '''import json
import re
import logging
from collections import Counter

from hermes_agent.llm_output_contract import llm_output_failure'''

OLD_BLOCK = '''        try:
            result = self.llm.analyze(
                "You are a universal fact extractor. Extract substantive facts only. Normalize keys to short snake_case names.",
                prompt,
                temperature=0.1,
            )

            logger.info("=" * 80)
            logger.info("[RAW EXTRACT RESPONSE]")
            logger.info(result["content"])
            logger.info("=" * 80)
            all_kvs = extract_json(result["content"])'''

NEW_BLOCK = '''        try:
            # PATCH 5: retry-before-give-up with an adaptive output
            # budget, mirroring PATCH 4/4c's TaskPlanner pattern. Retry
            # fires only on a call exception or a detected output-
            # contract failure (empty content / non-string content /
            # finish_reason == "length") -- NOT just because
            # extract_json() ends up returning {} on an otherwise-clean
            # response, since a genuinely fact-free evidence page is a
            # valid outcome (extractor rule 8), not a bug.
            extraction_max_tokens_schedule = [1024, 2048]
            all_kvs = {}
            # "content": "" so the SECOND logger.info(result["content"])
            # block further down (unchanged, pre-existing debug logging)
            # does not KeyError if every attempt is exhausted -- that
            # case must fall through as a clean empty-facts result, not
            # get mistaken for an exception in server.log.
            result = {"content": "", "tokens_input": 0, "tokens_output": 0, "api_cost": 0}
            for extract_attempt in range(1, len(extraction_max_tokens_schedule) + 1):
                attempt_max_tokens = extraction_max_tokens_schedule[extract_attempt - 1]
                try:
                    attempt_result = self.llm.analyze(
                        "You are a universal fact extractor. Extract substantive facts only. Normalize keys to short snake_case names.",
                        prompt,
                        temperature=0.1,
                        max_tokens=attempt_max_tokens,
                    )
                except Exception as e:
                    logger.warning(
                        f"[extract] call failed (attempt {extract_attempt}/{len(extraction_max_tokens_schedule)}, "
                        f"max_tokens={attempt_max_tokens}): {e}"
                    )
                    continue

                result = attempt_result

                failure = llm_output_failure(result)
                if failure is not None:
                    logger.warning(
                        f"[extract] output contract failed (attempt {extract_attempt}/{len(extraction_max_tokens_schedule)}, "
                        f"max_tokens={attempt_max_tokens}): {failure}"
                    )
                    continue

                logger.info("=" * 80)
                logger.info("[RAW EXTRACT RESPONSE]")
                logger.info(result["content"])
                logger.info("=" * 80)
                all_kvs = extract_json(result["content"])
                break
            else:
                logger.warning(
                    f"[extract] all {len(extraction_max_tokens_schedule)} attempts exhausted, "
                    "proceeding with empty facts"
                )'''


def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    assert src.count(OLD_IMPORTS) == 1, (
        f"OLD_IMPORTS not found exactly once (found {src.count(OLD_IMPORTS)}) -- "
        "source has drifted, aborting without changes."
    )
    assert src.count(OLD_BLOCK) == 1, (
        f"OLD_BLOCK not found exactly once (found {src.count(OLD_BLOCK)}) -- "
        "source has drifted from what PATCH 1/2/3/3B applied, aborting without changes."
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{TARGET}.bak_patch5_factchecker_budget_{timestamp}"
    shutil.copy2(TARGET, backup_path)
    print(f"[backup] {backup_path}")

    new_src = src.replace(OLD_IMPORTS, NEW_IMPORTS, 1)
    new_src = new_src.replace(OLD_BLOCK, NEW_BLOCK, 1)

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
    print("PATCH 5 applied and compiles. NOT YET VERIFIED.")
    print("Next: regression re-running the CoinDesk-only evidence from trace")
    print("28be48030145e6762e3eb55ac235d805 through the REAL FactChecker.extract_facts_batch()")
    print("(FakeLLM returning the same truncated content on attempt 1 to prove the retry path,")
    print("or the real LLMAnalyzer with round-robin active) -- confirm bitcoin_price/")
    print("78,533.76 survives into EXTRACTED FACTS this time. THEN, separately, Synthesis")
    print("fail-closed-on-zero-facts (not yet touched by this patch).")


if __name__ == "__main__":
    main()

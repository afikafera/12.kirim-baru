"""
PATCH 4c (2026-09-08): TaskPlanner.plan() retry now passes an adaptive
max_tokens per attempt (512 on attempt 1, 1024 on attempt 2), using the
LLMAnalyzer.analyze(max_tokens=...) parameter the user added themselves.

Schedule is the user's own example numbers -- NOT claimed final. Watch
the next regression specifically for whether the overall fallback rate
moves relative to the PATCH-4-only baseline (5/8 fallback, no max_tokens
sent at all): capping attempt 1 at 512 could truncate a model that
would have completed naturally with no cap, trading one failure mode
for another. This patch does not attempt to answer that -- only the
next regression run does.

Does NOT touch llm_output_contract.py, does NOT touch _fallback(),
does NOT add Research Budget accounting (still pending, per the user's
sequencing, until this measures out).

Usage:
    cd ~/research-assistant
    python3 apply_patch4c_adaptive_max_tokens.py

Same safety pattern: timestamped backup, assert exact-match, write,
py_compile, automatic rollback on failure.
"""
import py_compile
import shutil
import sys
from datetime import datetime

TARGET = "hermes_agent/task_planner.py"

OLD_BLOCK = '''        # PATCH 4: validate/retry BEFORE _fallback() -- a truncated or
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

NEW_BLOCK = '''        # PATCH 4: validate/retry BEFORE _fallback() -- a truncated or
        # empty LLM response used to go straight to _fallback(), which
        # sets topic=goal (the full raw user question) as the search
        # query. Retrying first gives the 9router round-robin a chance
        # to land on a model that actually completes the JSON.
        #
        # PATCH 4c: each attempt requests a larger max_tokens than the
        # last (512, then 1024) -- an early example schedule, not a
        # final number, meant to bound a slow/expensive attempt without
        # waiting for a model's own (sometimes very large) default.
        max_attempts = 2
        max_tokens_schedule = [512, 1024]
        for attempt in range(1, max_attempts + 1):
            attempt_max_tokens = max_tokens_schedule[min(attempt - 1, len(max_tokens_schedule) - 1)]
            try:
                result = self.llm.analyze(
                    "Kamu knowledge planner. Return JSON only.",
                    prompt, temperature=0.2,
                    max_tokens=attempt_max_tokens,
                )
            except Exception as e:
                logger.warning(f"[task_planner] call failed (attempt {attempt}/{max_attempts}, max_tokens={attempt_max_tokens}): {e}")
                continue

            failure = llm_output_failure(result)
            if failure is not None:
                logger.warning(f"[task_planner] output contract failed (attempt {attempt}/{max_attempts}, max_tokens={attempt_max_tokens}): {failure}")
                continue

            try:
                text = result["content"].strip().replace("```json", "").replace("```", "")
                logger.info("[PLANNER RAW] %r", text)
                plan = json.loads(text)
                plan = normalize_plan_entity_anchor(plan, context)
                return plan
            except Exception as e:
                logger.warning(f"[task_planner] parse failed (attempt {attempt}/{max_attempts}, max_tokens={attempt_max_tokens}): {e}")
                continue

        logger.warning(f"[task_planner] all {max_attempts} attempts exhausted, falling back")
        return self._fallback(goal, context)'''


def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    assert src.count(OLD_BLOCK) == 1, (
        f"OLD_BLOCK not found exactly once (found {src.count(OLD_BLOCK)}) -- "
        "source has drifted from what PATCH 4 applied, aborting without changes."
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{TARGET}.bak_patch4c_adaptive_max_tokens_{timestamp}"
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
    print("PATCH 4c applied and compiles. NOT YET VERIFIED.")
    print("Next: re-run regression_patch4_planner.py (same script, unchanged) and compare")
    print("against the PATCH-4-only baseline: fallback 5/8, raw_goal_leaked 5/8.")
    print("Watch server.log [task_planner] lines for 'max_tokens=512' / 'max_tokens=1024'")
    print("to confirm the schedule is actually being sent, and check whether the SAME")
    print("models that succeeded unbounded before now truncate at 512 (regression) or")
    print("whether models that used to hit 256 now succeed at 512/1024 (improvement).")


if __name__ == "__main__":
    main()

"""
PATCH 4 production regression: TaskPlanner.plan() called through the
REAL wired classes (config.load_config() -> real LLMAnalyzer -> real
TaskPlanner), 9router round-robin left fully active -- nothing stubbed,
nothing bypassed except everything downstream of the planner (this
isolates the planner alone, matching the established regression
pattern for this project).

Repeats N_RUNS times because round-robin means a single success/failure
is not proof of anything -- different runs can land on different
models with different capability.

For each run, reports:
  - elapsed time
  - whether plan.get("planner_fallback") is True (both attempts inside
    plan() were exhausted and it fell through to _fallback())
  - whether the raw GOAL string leaked into knowledge_required[].topic
    (the specific dangerous pattern PATCH 4 targets -- this is the
    thing that poisons the search query downstream)
  - the resulting topics, for manual inspection

This script does NOT capture which model/provider 9router selected per
attempt, or whether a retry actually fired inside plan() (attempt 1
failed, attempt 2 succeeded) -- that detail lives in server.log via the
existing [LLM] selected=... and [task_planner] ... log lines. Grep
server.log between the printed Start/End timestamps to see it.

Run:
    cd ~/research-assistant
    python3 regression_patch4_planner.py
"""
import sys
import time

sys.path.insert(0, ".")

import config
from llm_analyzer.analyzer import LLMAnalyzer
from hermes_agent.task_planner import TaskPlanner

GOAL = (
    "Cari harga BTC saat ini. Gunakan web untuk mengambil data aktual, "
    "sebutkan sumber, lalu bandingkan minimal 2 sumber. "
    "Jangan jawab dari knowledge internal."
)
N_RUNS = 8


def main():
    cfg = config.load_config()
    llm = LLMAnalyzer(cfg)
    planner = TaskPlanner(llm)

    print(f"=== PATCH 4 regression: TaskPlanner.plan() x{N_RUNS}, round-robin ACTIVE ===")
    print(f"Goal: {GOAL!r}")
    start_ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"Start: {start_ts} (local)")
    print("Grep server.log around this window for [LLM] selected=... and")
    print("[task_planner] ... lines to see per-attempt model + whether a retry fired.")
    print()

    results = []
    for i in range(1, N_RUNS + 1):
        t0 = time.time()
        try:
            plan = planner.plan(GOAL, context="")
            elapsed = time.time() - t0
            fallback = bool(plan.get("planner_fallback"))
            topics = [k.get("topic", "") for k in plan.get("knowledge_required", [])]
            raw_goal_leaked = any(t.strip() == GOAL.strip() for t in topics)
            results.append({
                "run": i, "elapsed_s": round(elapsed, 1), "fallback": fallback,
                "raw_goal_leaked": raw_goal_leaked, "topics": topics,
                "confidence": plan.get("confidence"), "error": None,
            })
        except Exception as e:
            elapsed = time.time() - t0
            results.append({
                "run": i, "elapsed_s": round(elapsed, 1), "fallback": None,
                "raw_goal_leaked": None, "topics": None,
                "confidence": None, "error": repr(e),
            })

    print(f"{'run':4s} {'elapsed_s':10s} {'fallback':9s} {'raw_goal_leaked':16s} topics")
    print("-" * 100)
    n_fallback = 0
    n_leaked = 0
    n_error = 0
    for r in results:
        if r["error"]:
            n_error += 1
            print(f"{r['run']:<4d} {r['elapsed_s']:<10} ERROR: {r['error']}")
            continue
        if r["fallback"]:
            n_fallback += 1
        if r["raw_goal_leaked"]:
            n_leaked += 1
        print(f"{r['run']:<4d} {r['elapsed_s']:<10} {str(r['fallback']):<9s} {str(r['raw_goal_leaked']):<16s} {r['topics']}")

    print("-" * 100)
    print(f"Total runs: {N_RUNS}")
    print(f"planner_fallback fired: {n_fallback}/{N_RUNS}")
    print(f"raw goal leaked as topic: {n_leaked}/{N_RUNS}  <-- the dangerous pattern PATCH 4 targets")
    print(f"exceptions: {n_error}/{N_RUNS}")
    print()
    end_ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"End: {end_ts} (local)")
    print(f"Now grep server.log between {start_ts} and {end_ts} for [task_planner] lines")
    print("(look for 'call failed' / 'output contract failed' / 'parse failed' followed by a")
    print("SUCCESSFUL attempt on the same run -- that is retry-before-fallback actually working)")
    print("and for [LLM] selected=... to confirm which providers/models 9router picked per attempt.")


if __name__ == "__main__":
    main()

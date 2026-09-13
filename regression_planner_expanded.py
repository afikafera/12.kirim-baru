"""
Expanded PATCH 4/4b-i/4c planner regression -- 12 goals x N_RUNS_PER_GOAL
controlled runs, covering: factual single-fact, comparison of 2+
sources, current/live data, source-constrained requests, Indonesian,
English, technical research, product-specific research, multi-
requirement requests, and explicit "don't answer from internal
knowledge" prohibition -- per the user's 2026-09-08 plan (successor to
the old informal "10 questions x 8 runs = 80/80" baseline evaluation
methodology, not a literal file/suite).

Uses the REAL config.load_config() -> real LLMAnalyzer -> real
TaskPlanner, round-robin 9router fully active -- nothing stubbed. A
thin duck-typed spy wraps LLMAnalyzer.analyze() PURELY to record
model/finish_reason/tokens/contract-classification per underlying LLM
call; it does not change what TaskPlanner does or how it decides
anything -- every call still goes through the real analyze().

This validates the PLANNER control-plane only (PATCH 4/4b-i/4c) -- not
Search/Fetch/Evidence/FactChecker/Synthesis. That is a separate, later
regression per the user's plan, only after this one is stable.

Run:
    cd ~/research-assistant
    python3 regression_planner_expanded.py
"""
import sys
import time

sys.path.insert(0, ".")

import config
from llm_analyzer.analyzer import LLMAnalyzer
from hermes_agent.task_planner import TaskPlanner
from hermes_agent.llm_output_contract import llm_output_failure

N_RUNS_PER_GOAL = 5

GOALS = [
    ("ID_factual_single",
     "Berapa titik didih air pada tekanan atmosfer normal dalam derajat Celsius?"),
    ("ID_comparison_current_prohibition",
     "Cari harga BTC saat ini. Gunakan web untuk mengambil data aktual, "
     "sebutkan sumber, lalu bandingkan minimal 2 sumber. "
     "Jangan jawab dari knowledge internal."),
    ("ID_current_data",
     "Berapa harga emas (XAU/USD) saat ini per troy ounce? Sebutkan sumbernya."),
    ("ID_source_constrained",
     "Cari spesifikasi resmi Raspberry Pi 5 hanya dari situs resmi raspberrypi.com."),
    ("EN_technical",
     "Explain how TCP CUBIC congestion control works, and cite the relevant RFC number."),
    ("EN_comparison_current",
     "What is the current price of Ethereum (ETH) in USD? Use the web and "
     "compare at least two independent sources."),
    ("EN_source_constrained",
     "Find the official technical specifications of the Raspberry Pi 5 "
     "only from raspberrypi.com."),
    ("ID_product_specific",
     "Cari spesifikasi baterai (kapasitas Wh) untuk laptop ASUS ROG "
     "Zephyrus G14 tahun 2026."),
    ("EN_multi_requirement",
     "Find 3 popular async-capable Python web frameworks, list their pros "
     "and cons, and compare their performance benchmarks."),
    ("ID_multi_requirement_prohibition",
     "Cari 3 rekomendasi VPN gratis untuk streaming, sebutkan kelebihan "
     "dan kekurangan masing-masing dari web, jangan jawab dari "
     "pengetahuan internal."),
    ("EN_factual_single",
     "What is the boiling point of nitrogen in Kelvin?"),
    ("ID_technical_source_constrained",
     "Jelaskan cara kerja algoritma congestion control CUBIC di TCP, "
     "kutip nomor RFC resmi dari IETF."),
]


class _AnalyzeSpy:
    """Transparent wrapper around the REAL LLMAnalyzer instance -- every
    call passes straight through unchanged; this only records what came
    back, so the test can report model/finish_reason/tokens per
    underlying LLM call without touching TaskPlanner's own retry/
    contract logic at all."""

    def __init__(self, real_llm):
        self._real_llm = real_llm
        self.calls = []

    def analyze(self, *args, **kwargs):
        result = self._real_llm.analyze(*args, **kwargs)
        is_dict = isinstance(result, dict)
        content = result.get("content") if is_dict else None
        self.calls.append({
            "model": result.get("model") if is_dict else None,
            "requested_model": result.get("requested_model") if is_dict else None,
            "finish_reason": result.get("finish_reason") if is_dict else None,
            "tokens_output": result.get("tokens_output") if is_dict else None,
            "content_type": type(content).__name__,
            "contract_failure": llm_output_failure(result) if is_dict else "not_a_dict",
        })
        return result


def run_one(llm, goal_text):
    spy = _AnalyzeSpy(llm)
    planner = TaskPlanner(spy)

    t0 = time.time()
    error = None
    plan = None
    try:
        plan = planner.plan(goal_text, context="")
    except Exception as e:
        error = repr(e)
    elapsed = time.time() - t0

    if error:
        return {
            "elapsed_s": round(elapsed, 1), "error": error, "fallback": None,
            "raw_goal_leaked": None, "topics": None, "confidence": None,
            "n_llm_calls": len(spy.calls), "calls": spy.calls,
            "first_call_contract_failure": None, "parse_failed_attempt1": None,
        }

    fallback = bool(plan.get("planner_fallback"))
    topics = [k.get("topic", "") for k in plan.get("knowledge_required", [])]
    raw_goal_leaked = any(t.strip() == goal_text.strip() for t in topics)

    first_call_contract_failure = spy.calls[0]["contract_failure"] if spy.calls else None
    parse_failed_attempt1 = bool(
        len(spy.calls) >= 2 and first_call_contract_failure is None
    )

    return {
        "elapsed_s": round(elapsed, 1), "error": None, "fallback": fallback,
        "raw_goal_leaked": raw_goal_leaked, "topics": topics,
        "confidence": plan.get("confidence"),
        "n_llm_calls": len(spy.calls), "calls": spy.calls,
        "first_call_contract_failure": first_call_contract_failure,
        "parse_failed_attempt1": parse_failed_attempt1,
    }


def main():
    cfg = config.load_config()
    llm = LLMAnalyzer(cfg)

    total_runs = len(GOALS) * N_RUNS_PER_GOAL
    print(f"=== Expanded planner regression: {len(GOALS)} goals x {N_RUNS_PER_GOAL} runs "
          f"= {total_runs} controlled runs ===")
    start_ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"Start: {start_ts} (local)\n")

    all_rows = []
    for label, goal_text in GOALS:
        print(f"--- {label} ---")
        print(f"  goal: {goal_text!r}")
        for run_i in range(1, N_RUNS_PER_GOAL + 1):
            r = run_one(llm, goal_text)
            r["label"] = label
            r["run"] = run_i
            all_rows.append(r)
            if r["error"]:
                print(f"  run {run_i}: ERROR {r['error']}")
            else:
                models = [c["model"] for c in r["calls"]]
                print(f"  run {run_i}: elapsed={r['elapsed_s']}s fallback={r['fallback']} "
                      f"raw_goal_leaked={r['raw_goal_leaked']} n_calls={r['n_llm_calls']} models={models}")
        print()

    end_ts = time.strftime("%Y-%m-%d %H:%M:%S")

    total = len(all_rows)
    n_error = sum(1 for r in all_rows if r["error"])
    n_fallback = sum(1 for r in all_rows if r.get("fallback"))
    n_leaked = sum(1 for r in all_rows if r.get("raw_goal_leaked"))
    n_success = total - n_error - n_fallback
    n_contract_fail_attempt1 = sum(
        1 for r in all_rows if not r["error"] and r.get("first_call_contract_failure") is not None
    )
    n_parse_fail_attempt1 = sum(1 for r in all_rows if not r["error"] and r.get("parse_failed_attempt1"))

    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(f"Total controlled runs   : {total}")
    print(f"Successful plans        : {n_success}/{total}")
    print(f"planner_fallback fired  : {n_fallback}/{total}")
    print(f"raw_goal_leaked         : {n_leaked}/{total}")
    print(f"exceptions              : {n_error}/{total}")
    print(f"attempt-1 contract fail : {n_contract_fail_attempt1}/{total}")
    print(f"attempt-1 parse fail    : {n_parse_fail_attempt1}/{total}")
    print()

    print(f"{'label':38s} {'success':8s} {'fallback':9s} {'leaked':7s} {'avg_s':6s}")
    print("-" * 100)
    for label, _ in GOALS:
        rows = [r for r in all_rows if r["label"] == label]
        succ = sum(1 for r in rows if not r["error"] and not r.get("fallback"))
        fb = sum(1 for r in rows if r.get("fallback"))
        lk = sum(1 for r in rows if r.get("raw_goal_leaked"))
        avg_s = round(sum(r["elapsed_s"] for r in rows) / len(rows), 1)
        print(f"{label:38s} {f'{succ}/{len(rows)}':8s} {fb:<9d} {lk:<7d} {avg_s:<6}")

    print()
    print(f"End: {end_ts} (local)")
    print(f"Grep server.log between {start_ts} and {end_ts} for [task_planner]/[LLM] lines")
    print("for full per-call detail (model selection, retry triggers).")


if __name__ == "__main__":
    main()

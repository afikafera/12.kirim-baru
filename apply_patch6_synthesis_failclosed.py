"""
PATCH 6 (2026-09-08): hermes_agent/orchestrator.py -- skip the synthesis
LLM call entirely and return a deterministic incomplete-status answer
when zero facts were extracted (DEFECT B).

PROVEN on two independent traces (28be48030145e6762e3eb55ac235d805 and
47b49071d6f3a15665268de66cdb2852): with EXTRACTED FACTS explicitly {},
every SOURCE MATERIAL entry marked "[content withheld: no verified
facts extracted from this source]", and explicit prompt rules already
in place ("Do not fabricate values", "Do not introduce technical
claims or inferences absent from EXTRACTED FACTS or SOURCE MATERIAL"),
the synthesis LLM still produced a complete fabricated answer both
times -- fake prices AND, in the second trace, a fake source
("CryptoSlate") that never appeared anywhere in the evidence or source
material for that run. Prompt-only enforcement is proven insufficient
on real production traffic with round-robin active; this patch adds a
code-level gate so there is no LLM in the loop that could hallucinate
when there is nothing to synthesize from.

Insertion point: hermes_agent/orchestrator.py, immediately after the
existing "[AUDIT SYNTHESIS]" logger.info call (confirmed unique, 1
occurrence in the file) and before the synthesis prompt/evidence text
is built. `all_facts` is the same dict already used a few lines below
for "{len(all_facts)} facts collected." / EXTRACTED FACTS in the
synthesis prompt -- `not all_facts` is exactly the zero-facts condition
observed in both traces. `missing` (list of unmet requirement_audit
entries) and `requirement_audit` are already computed above this point
in the same function; reused here, not recomputed. The early return
builds the exact same result-dict shape as the function's normal
ending (goal/answer/facts_count/iterations/pipeline/graph_stats/
token_profile/latency_profile/api_cost/duration_ms), calling
kg.save() and log_event("research_done", ...) the same way, so
callers see a consistent shape whether or not synthesis ran.
LatencyProfiler.summary() and TokenProfiler.summary()/.total_cost were
read directly (hermes_agent/latency_profiler.py,
hermes_agent/token_profiler.py) and confirmed safe to call with no
"synthesis" entry ever added (empty/missing-key-safe aggregation, no
KeyError, no division by zero).

Does NOT touch FactChecker/PATCH5 (separate, prior patch, extraction-
reliability work still open per the trace -- non-JSON-prose output and
wrong-key JSON arrays each silently lose facts independently of
PATCH5's retry, not addressed here). Does NOT touch TaskPlanner,
CompletenessChecker, or the requirement-fulfillment evaluator. Does
NOT change behavior at all for any run where at least one fact was
extracted -- the existing synthesis path (system_prompt with RESEARCH
STATUS: INCOMPLETE + strict rules) is left completely unchanged for
that case.

Usage:
    cd ~/research-assistant
    python3 apply_patch6_synthesis_failclosed.py

Same safety pattern: timestamped backup, assert exact-match, write,
py_compile, automatic rollback on failure.
"""
import py_compile
import shutil
import sys
from datetime import datetime

TARGET = "hermes_agent/orchestrator.py"

OLD_BLOCK = '''        logger.info(
            "[AUDIT SYNTHESIS] total_all_facts=%d own_request_facts=%d foreign_facts=%d "
            "nodes_this_request=%d nodes_total_in_kg=%d",
            len(all_facts), _own, len(all_facts) - _own,
            len(_this_request_nodes), len(kg.graph["nodes"]),
        )'''

NEW_BLOCK = '''        logger.info(
            "[AUDIT SYNTHESIS] total_all_facts=%d own_request_facts=%d foreign_facts=%d "
            "nodes_this_request=%d nodes_total_in_kg=%d",
            len(all_facts), _own, len(all_facts) - _own,
            len(_this_request_nodes), len(kg.graph["nodes"]),
        )

        # PATCH 6: fail-closed on zero extracted facts. Proven live on two
        # independent traces that the synthesis LLM fabricates a complete
        # answer (fake prices, fake sources not present anywhere in the
        # evidence) even when EXTRACTED FACTS is explicitly {} and the
        # prompt already forbids fabrication -- prompt-only enforcement is
        # not enough. Skip the synthesis LLM call entirely in this case and
        # return a deterministic incomplete-status answer built only from
        # requirement_audit/missing (already computed above), so there is
        # no LLM in the loop that could hallucinate when there is nothing
        # to synthesize from.
        if not all_facts:
            logger.warning(
                "[SYNTHESIS SKIP] zero facts extracted -- returning incomplete "
                "status without calling the synthesis LLM"
            )
            missing_topics = [r["topic"] for r in missing] or [
                r["topic"] for r in requirement_audit
            ]
            if missing_topics:
                answer = (
                    "Riset tidak dapat diselesaikan: tidak ada fakta terverifikasi "
                    "yang berhasil diekstrak dari sumber yang ditemukan.\\n\\n"
                    "Requirement yang belum terpenuhi:\\n"
                    + "\\n".join(f"- {t}" for t in missing_topics)
                )
            else:
                answer = (
                    "Riset tidak dapat diselesaikan: tidak ada fakta terverifikasi "
                    "yang berhasil diekstrak dari sumber yang ditemukan."
                )

            kg.save()

            log_event(
                "research_done",
                {
                    "goal": goal,
                    "pipeline": pipeline_type,
                    "iterations": iterations_completed,
                    "facts": 0,
                    "duration_ms": (time.time() - t0_total) * 1000,
                },
            )

            return {
                "goal": goal, "answer": answer,
                "facts_count": 0, "iterations": iterations_completed,
                "pipeline": pipeline_type, "graph_stats": kg.get_stats(),
                "token_profile": profiler.summary(), "latency_profile": latency.summary(),
                "api_cost": profiler.total_cost, "duration_ms": (time.time() - t0_total) * 1000,
            }'''


def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    assert src.count(OLD_BLOCK) == 1, (
        f"OLD_BLOCK not found exactly once (found {src.count(OLD_BLOCK)}) -- "
        "source has drifted from what was audited, aborting without changes."
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{TARGET}.bak_patch6_synthesis_failclosed_{timestamp}"
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
    print("PATCH 6 applied and compiles. NOT YET VERIFIED.")
    print("Next: regression -- re-run a BTC-price-style goal end to end at least once")
    print("with round-robin active. Confirm two things in server.log / the returned")
    print("result: (1) when facts > 0, output is UNCHANGED (synthesis LLM still called,")
    print("same prompt as before); (2) when facts == 0, '[SYNTHESIS SKIP]' appears in")
    print("the log, the synthesis LLM is NOT called (no new [LLM CALLER] line for the")
    print("synthesis call site), and the returned answer explicitly reports missing")
    print("requirements instead of any fabricated price/source.")


if __name__ == "__main__":
    main()

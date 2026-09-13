"""
CONTROLLED PRODUCTION REGRESSION -- PATCH 1 (hermes_agent/fact_checker.py)

Purpose: prove PATCH 1 actually works at runtime, using the REAL production
classes (LLMAnalyzer with the real round-robin providers, real FactChecker
with PATCH 1 already applied), WITHOUT going through Planner/Search/
Synthesis. This sidesteps the unrelated Planner finish_reason=length
truncation defect (already flagged separately, not being touched here) and
never touches MemoryManager/KnowledgeGraph (no DB/lock involvement at all).

What is real vs controlled:
  - REAL: config.load_config() (reads the actual .env), LLMAnalyzer(config)
    (actual round-robin providers), FactChecker(llm) (actual patched class
    from hermes_agent/fact_checker.py).
  - CONTROLLED: the "evidence" passed in is a fixed dict matching the exact
    production case (subenclosure.net port formula page for ACR 12500
    Black), so the input is reproducible even though the LLM's output is
    not (round-robin means a different downstream model may answer the
    same prompt differently each run -- this is why the script repeats
    the call several times rather than trusting a single sample).

This does NOT modify search/planner/synthesis and does NOT add a second
LLM-based verifier -- it only calls the extractor that already exists.

Run ON THE SERVER, same environment as the live app:
    cd ~/research-assistant
    python3 production_regression_factchecker_patch1.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.expanduser("~/research-assistant"))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)

from config import load_config  # noqa: E402
from llm_analyzer.analyzer import LLMAnalyzer  # noqa: E402
from hermes_agent.fact_checker import FactChecker  # noqa: E402

RUNS = 5

EVIDENCE = [
    {
        "url": "https://subenclosure.net/port-formula-test",
        "content": (
            "Standard formula: L = (23,562 x D^2) / (Fb^2 x Vb) - 0.732D. "
            "Example: 4-inch port, 35 Hz tuning, 1.5 cf net. "
            "Material: MDF. Port type: Slot."
        ),
        "doc_type": "forum",
    }
]


def main():
    config = load_config()
    llm = LLMAnalyzer(config)
    fc = FactChecker(llm)

    summary = []

    for i in range(1, RUNS + 1):
        print("=" * 90)
        print(f"RUN {i}/{RUNS}")
        print("=" * 90)

        facts, result = fc.extract_facts_batch(EVIDENCE, [])

        print(f"model used: {result.get('model')}")
        print("raw LLM response:")
        print(result.get("content"))
        print()
        print(f"VALIDATED FACTS (total={len(facts)}):")
        for k, v in facts.items():
            print(f"  {k} = {v}")
        print()

        fabricated_caught = "port_width" not in facts and "port_height" not in facts
        legit_survived = facts.get("port_diameter", {}).get("value") == "4-inch"

        summary.append({
            "run": i,
            "total_facts": len(facts),
            "has_fabricated_12inch": ("port_width" in facts) or ("port_height" in facts),
            "fabricated_caught": fabricated_caught,
            "legit_port_diameter_survived": legit_survived,
        })

    print("=" * 90)
    print("SUMMARY ACROSS RUNS")
    print("=" * 90)
    for s in summary:
        print(s)

    any_fabricated_leaked = any(s["has_fabricated_12inch"] for s in summary)
    print()
    if any_fabricated_leaked:
        print("[ATTENTION] At least one run still contains a fabricated 12-inch "
              "port_width/port_height fact. Check the [FACT REJECT] log lines "
              "above for that run and inspect whether the LLM phrased the value "
              "in a way the numeric fidelity gate did not catch (e.g. spelled "
              "out as 'twelve inch', or a different source URL substitution).")
    else:
        print("[OK] No run produced a surviving fabricated 12-inch port_width/"
              "port_height fact. Check above for [FACT REJECT] ... "
              "reason=value_not_in_evidence log lines to confirm the gate is "
              "what caught it (vs. the LLM simply not fabricating it this time).")


if __name__ == "__main__":
    main()

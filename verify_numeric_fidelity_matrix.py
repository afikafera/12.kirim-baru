"""
DETERMINISTIC REGRESSION TEST -- numeric fidelity matrix, against the REAL
production hermes_agent/fact_checker.py (imports the actual patched
_value_supported_by_source() and FactChecker directly, no reimplementation).

Resolves the matrix from the "AUDIT numeric semantics" conclusion:

  SOURCE       LLM          EXPECTED    WHY
  23,562       23,562       ACCEPT      exact match, rule 9 honored
  23,562       23.562       REJECT      rule 9 violated (not preserved exactly,
                                         regardless of locale-equivalence)
  23.562       23.562       ACCEPT      exact match
  23.562       23,562       REJECT      same reasoning, symmetric
  12-inch      12-inch      ACCEPT      exact match
  (no 12")     12-inch      REJECT      original target defect

Rule 9 (already in production, hermes_agent/fact_checker.py's
extract_facts_batch() prompt): "Preserve exact numeric values, units, URLs,
commands, and technical terms from the evidence." The gate's job is to
verify exact preservation, not locale-equivalence -- so both comma/period
conversion directions are expected to REJECT.

PART 1 -- pure function test of _value_supported_by_source() directly.
  Fully deterministic, no LLM involved. This is the actual regression proof
  for the matrix.

PART 2 -- end-to-end sanity check via FakeLLM + extract_facts_batch(),
  confirming the gate is correctly wired into the full pipeline for the
  original target defect (fabricated port dimensions), not just correct in
  isolation.

No code changes. No LLM calls. No search/planner/synthesis involvement.

Run ON THE SERVER (needs the real hermes_agent package importable):
    cd ~/research-assistant
    python3 verify_numeric_fidelity_matrix.py
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/research-assistant"))

from hermes_agent.fact_checker import FactChecker, _value_supported_by_source  # noqa: E402


# ---------------------------------------------------------------------------
# PART 1: deterministic matrix test of _value_supported_by_source()
# ---------------------------------------------------------------------------

MATRIX = [
    {
        "label": "23,562 (source) vs 23,562 (LLM) -- exact match",
        "value": "L = 23,562 x D",
        "source_content": "Standard formula: L = (23,562 x D^2) / (Fb^2 x Vb) - 0.732D.",
        "expected": True,
    },
    {
        "label": "23,562 (source) vs 23.562 (LLM) -- comma->period, rule 9 violation",
        "value": "L = 23.562 x D",
        "source_content": "Standard formula: L = (23,562 x D^2) / (Fb^2 x Vb) - 0.732D.",
        "expected": False,
    },
    {
        "label": "23.562 (source) vs 23.562 (LLM) -- exact match",
        "value": "L = 23.562 x D",
        "source_content": "Standard formula: L = (23.562 x D^2) / (Fb^2 x Vb) - 0.732D.",
        "expected": True,
    },
    {
        "label": "23.562 (source) vs 23,562 (LLM) -- period->comma, rule 9 violation",
        "value": "L = 23,562 x D",
        "source_content": "Standard formula: L = (23.562 x D^2) / (Fb^2 x Vb) - 0.732D.",
        "expected": False,
    },
    {
        "label": "12-inch present in source, LLM claims 12-inch -- exact match",
        "value": "12-inch",
        "source_content": "The enclosure requires a 12-inch wide, 12-inch tall slot port.",
        "expected": True,
    },
    {
        "label": "no 12 anywhere in source, LLM claims 12-inch -- fabrication",
        "value": "12-inch",
        "source_content": "Standard formula: L = (23,562 x D^2) / (Fb^2 x Vb) - 0.732D. "
                           "Example: 4-inch port, 35 Hz tuning, 1.5 cf net. "
                           "Material: MDF. Port type: Slot.",
        "expected": False,
    },
]


def run_part1():
    print("=" * 90)
    print("PART 1: _value_supported_by_source() matrix (deterministic, no LLM)")
    print("=" * 90)
    failures = 0
    for case in MATRIX:
        actual = _value_supported_by_source(case["value"], case["source_content"])
        status = "PASS" if actual == case["expected"] else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"[{status}] {case['label']}")
        print(f"        value={case['value']!r}")
        print(f"        expected={case['expected']} actual={actual}")
        print()
    return failures


# ---------------------------------------------------------------------------
# PART 2: end-to-end sanity check via FakeLLM + extract_facts_batch()
# ---------------------------------------------------------------------------

class FakeLLM:
    def __init__(self, raw_content: str):
        self.raw_content = raw_content

    def analyze(self, system, prompt, temperature=0.1):
        return {
            "content": self.raw_content,
            "model": "test", "requested_model": "test",
            "tokens_input": 0, "tokens_output": 0, "api_cost": 0,
        }


def run_part2():
    print("=" * 90)
    print("PART 2: end-to-end via extract_facts_batch() (FakeLLM, deterministic)")
    print("=" * 90)

    url = "https://subenclosure.net/port-formula-test"
    source_content = (
        "Standard formula: L = (23,562 x D^2) / (Fb^2 x Vb) - 0.732D. "
        "Example: 4-inch port, 35 Hz tuning, 1.5 cf net. "
        "Material: MDF. Port type: Slot."
    )
    evidence = [{"url": url, "content": source_content, "doc_type": "forum"}]

    import json
    raw = json.dumps({
        "port_diameter": {"value": "4-inch", "source": url, "source_type": "forum"},
        "port_width": {"value": "12-inch", "source": url, "source_type": "forum"},
        "port_height": {"value": "12-inch", "source": url, "source_type": "forum"},
        "formula_constant_exact": {"value": "23,562", "source": url, "source_type": "forum"},
        "formula_constant_reformatted": {"value": "23.562", "source": url, "source_type": "forum"},
    })

    fc = FactChecker(FakeLLM(raw))
    facts, _ = fc.extract_facts_batch(evidence, [])

    print(f"VALIDATED FACTS (total={len(facts)}):")
    for k, v in facts.items():
        print(f"  {k} = {v}")
    print()

    failures = 0

    def check(cond, msg):
        nonlocal failures
        print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            failures += 1

    check("port_width" not in facts, "fabricated port_width=12-inch rejected")
    check("port_height" not in facts, "fabricated port_height=12-inch rejected")
    check(facts.get("port_diameter", {}).get("value") == "4-inch", "legitimate port_diameter=4-inch survives")
    check("formula_constant_exact" in facts, "exact-preserved 23,562 survives (matches source verbatim)")
    check("formula_constant_reformatted" not in facts, "reformatted 23.562 rejected (rule 9: not preserved exactly)")

    return failures


if __name__ == "__main__":
    failures_1 = run_part1()
    failures_2 = run_part2()

    print("=" * 90)
    total_failures = failures_1 + failures_2
    if total_failures == 0:
        print("ALL MATRIX + END-TO-END CASES PASSED")
    else:
        print(f"{total_failures} CASE(S) FAILED -- see [FAIL] lines above")
    print("=" * 90)

    sys.exit(1 if total_failures else 0)

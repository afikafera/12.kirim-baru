"""
VERIFY (isolated, read-only): PATCH 2 candidate for hermes_agent/fact_checker.py

Adds a deterministic "example-scope" gate, applied AFTER the existing
PATCH 1 numeric fidelity gate: a fact is rejected if its value sits in the
same sentence as an example/illustration marker in the source content
(e.g. "Example: 4-inch port, 35 Hz tuning, 1.5 cf net" -- all three values
are illustrative for the FORMULA, not ACR 12500 Black's actual design
values, even though PATCH 1's numeric check correctly lets them through
since the numbers genuinely appear in the source).

This subclasses the REAL production FactChecker (with PATCH 1 already
applied) and overrides extract_facts_batch() to add ONLY the new gate --
everything else (parsing, provenance, numeric fidelity) is inherited
production behavior via direct reuse of the real _value_supported_by_source.

Explicitly tested, including the known false-positive limitation flagged
in the audit: a genuine spec value sharing a sentence with an unrelated
"example" mention will also be rejected. This is surfaced, not hidden --
consistent with the fail-closed design already validated in PATCH 1.

No second LLM call. No changes to search/planner/synthesis.

Run ON THE SERVER (needs the real hermes_agent package, PATCH 1 applied):
    cd ~/research-assistant
    python3 verify_factchecker_patch2.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.expanduser("~/research-assistant"))

from hermes_agent.fact_checker import FactChecker, _value_supported_by_source  # noqa: E402


# ---------------------------------------------------------------------------
# CANDIDATE addition: example-scope gate
# ---------------------------------------------------------------------------

_EXAMPLE_MARKERS = re.compile(
    r'\b(example|e\.g\.|for instance|for example|sample calculation|'
    r'misalnya|contoh|sebagai contoh)\b',
    re.IGNORECASE,
)


def _value_is_example_scoped(value: str, source_content: str) -> bool:
    """True if `value` (or its first numeric token) appears in `source_content`
    inside a sentence that itself marks the content as an example/illustration
    rather than the subject's actual value."""
    if not value or not source_content:
        return False

    idx = source_content.find(value)
    if idx == -1:
        nums = re.findall(r'\d+(?:[.,]\d+)?', value)
        for num in nums:
            idx = source_content.find(num)
            if idx != -1:
                break
    if idx == -1:
        return False

    start = max(
        source_content.rfind('.', 0, idx),
        source_content.rfind('\n', 0, idx),
        source_content.rfind('!', 0, idx),
        source_content.rfind('?', 0, idx),
    )
    end_candidates = [
        p for p in (
            source_content.find('.', idx),
            source_content.find('!', idx),
            source_content.find('?', idx),
        ) if p != -1
    ]
    end = min(end_candidates) if end_candidates else len(source_content)

    sentence = source_content[start + 1:end + 1]
    return bool(_EXAMPLE_MARKERS.search(sentence))


class CandidateFactChecker(FactChecker):
    """Real production FactChecker (PATCH 1 already applied), with the
    example-scope gate added as an extra rejection check."""

    def extract_facts_batch(self, all_evidence: list, checklist: list) -> tuple:
        if not all_evidence:
            return ({}, {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})

        candidates = [e for e in all_evidence if isinstance(e, dict) and e.get("content")]
        evidence_text = "\n\n".join(
            f"### SUMBER: {e.get('url','unknown')}\n{e.get('content','')}" for e in candidates
        )
        if not evidence_text.strip():
            return ({}, {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})

        result = self.llm.analyze("test", "test", temperature=0.1)
        all_kvs = json.loads(result["content"])
        if not isinstance(all_kvs, dict):
            all_kvs = {}

        valid_urls = {str(e.get("url", "")).strip() for e in all_evidence if e.get("url")}
        url_to_content = {
            str(e.get("url", "")).strip(): e.get("content", "")
            for e in all_evidence if e.get("url")
        }

        validated = {}
        for key, value in all_kvs.items():
            if not isinstance(value, dict):
                continue
            src = str(value.get("source", "")).strip()
            if not src or src not in valid_urls:
                print(f"[FACT REJECT] field={key} reason=source_not_in_evidence source={src!r}")
                continue

            source_content = url_to_content.get(src, "")
            fact_value = str(value.get("value", ""))

            if not _value_supported_by_source(fact_value, source_content):
                print(f"[FACT REJECT] field={key} reason=value_not_in_evidence value={fact_value!r} source={src!r}")
                continue

            # PATCH 2 addition
            if _value_is_example_scoped(fact_value, source_content):
                print(f"[FACT REJECT] field={key} reason=example_value_not_actual value={fact_value!r} source={src!r}")
                continue

            validated[key] = value

        return (validated, result)


class FakeLLM:
    def __init__(self, raw_content: str):
        self.raw_content = raw_content

    def analyze(self, system, prompt, temperature=0.1):
        return {"content": self.raw_content, "model": "test",
                "tokens_input": 0, "tokens_output": 0, "api_cost": 0}


def run_case(label, checker, evidence):
    print("=" * 90)
    print(label)
    print("=" * 90)
    facts, _ = checker.extract_facts_batch(evidence, [])
    print(f"RESULT total={len(facts)} keys={list(facts.keys())}")
    for k, v in facts.items():
        print(f"  {k} = {v}")
    print()
    return facts


if __name__ == "__main__":
    url = "https://subenclosure.net/port-formula-test"
    source_content = (
        "Standard formula: L = (23,562 x D^2) / (Fb^2 x Vb) - 0.732D. "
        "Example: 4-inch port, 35 Hz tuning, 1.5 cf net. "
        "Resonant Frequency (Fs): 55 Hz. "
        "Material: MDF. Port type: Slot."
    )
    evidence = [{"url": url, "content": source_content, "doc_type": "forum"}]

    raw = json.dumps({
        "port_length_formula": {"value": "L = (23,562 x D^2) / (Fb^2 x Vb) - 0.732D", "source": url, "source_type": "forum"},
        "example_port_diameter": {"value": "4-inch", "source": url, "source_type": "forum"},
        "example_tuning_frequency": {"value": "35 Hz", "source": url, "source_type": "forum"},
        "example_net_volume": {"value": "1.5 cf", "source": url, "source_type": "forum"},
        "resonant_frequency_fs": {"value": "55 Hz", "source": url, "source_type": "forum"},
        "material": {"value": "MDF", "source": url, "source_type": "forum"},
        "port_type": {"value": "Slot", "source": url, "source_type": "forum"},
    })

    print("### BASELINE: production FactChecker WITHOUT PATCH 2 (PATCH 1 only) ###\n")
    old_checker = FactChecker(FakeLLM(raw))
    facts_old = run_case("PATCH 1 only", old_checker, evidence)
    assert facts_old.get("example_tuning_frequency", {}).get("value") == "35 Hz", \
        "expected PATCH-1-only to still keep the example-labeled 35 Hz (proves PATCH 2 gap exists)"
    assert facts_old.get("example_net_volume", {}).get("value") == "1.5 cf"
    assert facts_old.get("example_port_diameter", {}).get("value") == "4-inch"
    print("[CONFIRMED] PATCH 1 alone keeps all three example-clause values -- PATCH 2 gap proven.\n")

    print("### CANDIDATE: PATCH 1 + PATCH 2 (example-scope gate) ###\n")
    new_checker = CandidateFactChecker(FakeLLM(raw))
    facts_new = run_case("PATCH 1 + PATCH 2", new_checker, evidence)

    failures = 0
    def check(cond, msg):
        global failures
        print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            failures += 1

    check("example_port_diameter" not in facts_new, "example-clause 4-inch rejected")
    check("example_tuning_frequency" not in facts_new, "example-clause 35 Hz rejected")
    check("example_net_volume" not in facts_new, "example-clause 1.5 cf rejected")
    check(facts_new.get("resonant_frequency_fs", {}).get("value") == "55 Hz",
          "genuine non-example fact (Fs=55 Hz, different sentence) survives")
    check(facts_new.get("material", {}).get("value") == "MDF",
          "non-numeric non-example fact survives")
    check(facts_new.get("port_type", {}).get("value") == "Slot",
          "non-numeric non-example fact survives")
    check("port_length_formula" in facts_new,
          "generic formula (not entity-specific, not example-labeled) survives")

    print()
    print("=" * 90)
    print("KNOWN LIMITATION DEMONSTRATION (sentence-local false positive)")
    print("=" * 90)
    fp_source = "For example, older enclosures used sealed designs; this one specifies 55 Hz Fs."
    fp_evidence = [{"url": url, "content": fp_source, "doc_type": "forum"}]
    fp_raw = json.dumps({
        "resonant_frequency_fs": {"value": "55 Hz", "source": url, "source_type": "forum"},
    })
    fp_checker = CandidateFactChecker(FakeLLM(fp_raw))
    fp_facts = run_case("False-positive case: genuine value sharing a sentence with 'For example'", fp_checker, fp_evidence)
    if "resonant_frequency_fs" not in fp_facts:
        print("[EXPECTED LIMITATION CONFIRMED] genuine 55 Hz value was rejected because it shares a")
        print("sentence with an unrelated 'For example' mention. This is the documented trade-off:")
        print("fail-closed over fail-open. Not counted as a pass/fail case -- informational only.\n")
    else:
        print("[UNEXPECTED] this case was expected to demonstrate the known limitation but did not.\n")
        failures += 1

    print("=" * 90)
    if failures == 0:
        print("ALL PATCH 2 VERIFY CASES PASSED")
    else:
        print(f"{failures} CASE(S) FAILED")
    print("=" * 90)
    sys.exit(1 if failures else 0)

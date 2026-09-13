"""
VERIFY (isolated, read-only): PATCH 2b -- narrow semicolon-boundary fix
for the example-scope gate audited in verify_factchecker_patch2.py.

Decision (user-confirmed): add ';' to the clause-boundary character set
used by _value_is_example_scoped() (alongside '.', '!', '?', '\\n').
Explicitly NOT adding any contrastive-conjunction heuristic (but/however/
this model/this one) -- semicolon only, deterministic, minimal.

This subclasses the REAL production FactChecker (PATCH 1 already applied)
the same way verify_factchecker_patch2.py did, with only the boundary
character set changed in the candidate _value_is_example_scoped().

Required proof, exactly as specified:
  1. "For example, old designs; this one specifies 55 Hz"
     -> 55 Hz SURVIVES (semicolon now isolates the example clause from
        the genuine value clause)
  2. "Example: 4-inch port, 35 Hz tuning, 1.5 cf net."
     -> 4-inch / 35 Hz / 1.5 cf all REJECTED (target defect still caught,
        no semicolon present, this case must be unaffected)
  3. "For example, old designs. This one specifies 55 Hz."
     -> 55 Hz SURVIVES (already worked before the semicolon fix, kept
        here as a non-regression check)
  4. An ordinary non-example fact -> SURVIVES

No code changes to production. No LLM calls. No search/planner/synthesis
involvement.

Run ON THE SERVER (needs the real hermes_agent package, PATCH 1 applied):
    cd ~/research-assistant
    python3 verify_factchecker_patch2b_semicolon.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.expanduser("~/research-assistant"))

from hermes_agent.fact_checker import FactChecker, _value_supported_by_source  # noqa: E402


_EXAMPLE_MARKERS = re.compile(
    r'\b(example|e\.g\.|for instance|for example|sample calculation|'
    r'misalnya|contoh|sebagai contoh)\b',
    re.IGNORECASE,
)


def _value_is_example_scoped(value: str, source_content: str) -> bool:
    """PATCH 2b: same as the PATCH 2 candidate, with ';' added to the
    clause-boundary character set. No contrastive-conjunction heuristic
    added -- semicolon only, per the confirmed decision."""
    if not value or not source_content:
        return False

    idx = source_content.find(value)
    if idx == -1:
        for num in re.findall(r'\d+(?:[.,]\d+)?', value):
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
        source_content.rfind(';', 0, idx),
    )
    end_candidates = [
        p for p in (
            source_content.find('.', idx),
            source_content.find('!', idx),
            source_content.find('?', idx),
            source_content.find(';', idx),
        ) if p != -1
    ]
    end = min(end_candidates) if end_candidates else len(source_content)

    sentence = source_content[start + 1:end + 1]
    return bool(_EXAMPLE_MARKERS.search(sentence))


class CandidatePatch2b(FactChecker):
    def extract_facts_batch(self, all_evidence: list, checklist: list) -> tuple:
        if not all_evidence:
            return ({}, {})
        candidates = [e for e in all_evidence if isinstance(e, dict) and e.get("content")]
        if not candidates:
            return ({}, {})

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


def run_case(label, evidence, raw):
    print("=" * 90)
    print(label)
    print("=" * 90)
    checker = CandidatePatch2b(FakeLLM(raw))
    facts, _ = checker.extract_facts_batch(evidence, [])
    print(f"RESULT total={len(facts)} keys={list(facts.keys())}")
    for k, v in facts.items():
        print(f"  {k} = {v}")
    print()
    return facts


if __name__ == "__main__":
    url = "https://example.test/src"
    failures = 0

    def check(cond, msg):
        global failures
        print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            failures += 1

    # -------------------------------------------------------------
    # CASE 1: semicolon-compound sentence -- genuine value must survive
    # -------------------------------------------------------------
    src1 = "For example, old designs used sealed enclosures; this one specifies 55 Hz Fs."
    ev1 = [{"url": url, "content": src1, "doc_type": "forum"}]
    raw1 = json.dumps({"fs": {"value": "55 Hz", "source": url, "source_type": "forum"}})
    facts1 = run_case("CASE 1: semicolon-compound sentence", ev1, raw1)
    check("fs" in facts1, "55 Hz SURVIVES when isolated from 'For example' by a semicolon")

    # -------------------------------------------------------------
    # CASE 2: real target defect pattern -- must still be caught
    # -------------------------------------------------------------
    src2 = "Example: 4-inch port, 35 Hz tuning, 1.5 cf net."
    ev2 = [{"url": url, "content": src2, "doc_type": "forum"}]
    raw2 = json.dumps({
        "port_diameter": {"value": "4-inch", "source": url, "source_type": "forum"},
        "tuning_freq": {"value": "35 Hz", "source": url, "source_type": "forum"},
        "net_volume": {"value": "1.5 cf", "source": url, "source_type": "forum"},
    })
    facts2 = run_case("CASE 2: real target defect pattern (no semicolon)", ev2, raw2)
    check("port_diameter" not in facts2, "4-inch REJECTED (target defect unaffected by semicolon fix)")
    check("tuning_freq" not in facts2, "35 Hz REJECTED (target defect unaffected)")
    check("net_volume" not in facts2, "1.5 cf REJECTED (target defect unaffected)")

    # -------------------------------------------------------------
    # CASE 3: period-separated sentences -- non-regression check
    # -------------------------------------------------------------
    src3 = "For example, old designs used sealed enclosures. This one specifies 55 Hz Fs."
    ev3 = [{"url": url, "content": src3, "doc_type": "forum"}]
    raw3 = json.dumps({"fs": {"value": "55 Hz", "source": url, "source_type": "forum"}})
    facts3 = run_case("CASE 3: period-separated sentences (non-regression)", ev3, raw3)
    check("fs" in facts3, "55 Hz SURVIVES when in its own period-bounded sentence")

    # -------------------------------------------------------------
    # CASE 4: ordinary non-example fact -- must survive
    # -------------------------------------------------------------
    src4 = "Material: MDF. Port type: Slot."
    ev4 = [{"url": url, "content": src4, "doc_type": "forum"}]
    raw4 = json.dumps({
        "material": {"value": "MDF", "source": url, "source_type": "forum"},
        "port_type": {"value": "Slot", "source": url, "source_type": "forum"},
    })
    facts4 = run_case("CASE 4: ordinary non-example facts", ev4, raw4)
    check(facts4.get("material", {}).get("value") == "MDF", "MDF SURVIVES")
    check(facts4.get("port_type", {}).get("value") == "Slot", "Slot SURVIVES")

    print("=" * 90)
    if failures == 0:
        print("ALL PATCH 2b (semicolon-boundary) VERIFY CASES PASSED")
    else:
        print(f"{failures} CASE(S) FAILED")
    print("=" * 90)
    sys.exit(1 if failures else 0)

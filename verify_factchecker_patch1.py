"""
VERIFY (isolated, read-only): PATCH 1 candidate for hermes_agent/fact_checker.py

Tests, against the REAL production FactChecker class (imported directly from
~/research-assistant, not reimplemented), two independent defects:

  DEFECT 1 -- extract_json() bracket-order bug:
    A single-element JSON array response (with surrounding text) gets
    unwrapped incorrectly by the greedy r'\{.*\}' pattern tried first,
    producing a bare dict of fact-fields at the top level instead of a
    list. Downstream this silently drops all facts -> [PARSED FACTS] total=0.

  DEFECT 2 -- no value/content fidelity check:
    The current provenance guard only checks that a fact's "source" URL
    is among the URLs given to the extractor. It does NOT check that the
    fact's VALUE is actually present/supported in that source's content.
    Reproduces the real production case: subenclosure.net formula page
    (Standard formula + "Example: 4-inch port, 35 Hz tuning, 1.5 cf net")
    for the ACR 12500 Black query, where the LLM fabricated
    port_width=12-inch and port_height=12-inch (never mentioned anywhere
    in the source).

For each defect: run OLD (real, unmodified FactChecker.extract_facts_batch)
first to PROVE the bug reproduces, then run CANDIDATE (a subclass that
only swaps in the two smallest fixes) to PROVE it is resolved, and that
legitimately-sourced facts survive unchanged.

Explicitly NOT in scope for this patch (left as-is, verified untouched):
  - "35 Hz" / "1.5 cf" are labeled "Example:" in the source and are NOT
    actually ACR 12500 Black's real box tuning values. This is a separate
    example-vs-actual semantic issue (PATCH 2), deliberately not filtered
    here since PATCH 1 is a numeric-value-fidelity gate only, not a
    semantic/context classifier.
  - No second LLM call is introduced anywhere in this candidate.

Run ON THE SERVER (needs the real hermes_agent package importable):
    cd ~/research-assistant
    python3 verify_factchecker_patch1.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.expanduser("~/research-assistant"))

from hermes_agent.fact_checker import FactChecker  # noqa: E402


# ---------------------------------------------------------------------------
# CANDIDATE fixes (smallest possible, no new LLM dependency)
# ---------------------------------------------------------------------------

def candidate_extract_json(text: str):
    """Same as production extract_json(), except it tries the pattern
    matching whichever bracket ('{' or '[') appears FIRST in the text,
    instead of always trying the object pattern first."""
    try:
        return json.loads(text)
    except Exception:
        pass

    stripped_idx_brace = text.find('{')
    stripped_idx_bracket = text.find('[')

    if stripped_idx_bracket != -1 and (
        stripped_idx_brace == -1 or stripped_idx_bracket < stripped_idx_brace
    ):
        patterns = [r'\[.*\]', r'\{.*\}']
    else:
        patterns = [r'\{.*\}', r'\[.*\]']

    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return {}


NUM_PATTERN = re.compile(r'\d+(?:[.,]\d+)?')


def value_supported_by_source(value: str, source_content: str) -> bool:
    """Deterministic numeric fidelity gate: every numeric token present in
    the candidate value must literally appear in the cited source's raw
    content. Non-numeric values are out of scope for PATCH 1 and pass
    through unchanged (semantic/text validation is PATCH 2 territory)."""
    numbers = NUM_PATTERN.findall(value or "")
    if not numbers:
        return True
    haystack = source_content or ""
    return all(num in haystack for num in numbers)


class CandidateFactChecker(FactChecker):
    """Subclasses the REAL production FactChecker, overriding only
    extract_facts_batch() to apply the two PATCH 1 fixes. All other
    methods (evaluate, generate_gap_queries, generate_checklist) are
    inherited unmodified from production."""

    def extract_facts_batch(self, all_evidence: list, checklist: list) -> tuple:
        if not all_evidence:
            return ({}, {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})

        BAD_PATTERNS = (
            "error fetch", "error_fetch", "traceback", "access denied",
            "cloudflare", "captcha", "enable javascript", "request failed",
        )
        candidates = [
            e for e in all_evidence
            if isinstance(e, dict) and e.get("content")
            and not any(pat in e["content"].lower() for pat in BAD_PATTERNS)
        ]
        source_priority = {
            "datasheet": 5, "pdf": 5, "official_docs": 4, "manual": 4,
            "spec_table": 4, "catalog": 3, "forum": 2, "video": 1,
        }
        selected = sorted(
            candidates,
            key=lambda e: source_priority.get(
                str(e.get("evidence_type") or e.get("doc_type") or "").lower(), 0
            ),
            reverse=True,
        )[:self.MAX_EVIDENCE_SOURCES]

        evidence_blocks = []
        num_selected = max(1, len(selected))
        dynamic_limit = self.MAX_EVIDENCE_CHARS // num_selected
        per_source_limit = min(self.MAX_CHARS_PER_SOURCE, dynamic_limit)
        for i, e in enumerate(selected):
            source_type = e.get("evidence_type") or e.get("doc_type") or "other"
            header = f"### SUMBER {i+1}: {e.get('url', 'unknown')} (tipe: {source_type})\n"
            raw_content = e.get("content", "")
            paragraphs = raw_content.split("\n")
            source_text = header
            for p in paragraphs:
                if len(source_text) + len(p) + 1 <= per_source_limit:
                    source_text += p + "\n"
                else:
                    break
            evidence_blocks.append(source_text.strip())

        evidence_text = "\n\n".join(evidence_blocks)
        final_evidence = evidence_text
        if not final_evidence.strip():
            return ({}, {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})

        prompt = "TEST PROMPT (not sent to a real LLM in this harness)"

        try:
            result = self.llm.analyze(
                "You are a universal fact extractor.", prompt, temperature=0.1,
            )

            # DEFECT 1 FIX: candidate_extract_json instead of production extract_json
            all_kvs = candidate_extract_json(result["content"])

            if isinstance(all_kvs, list):
                normalized = {}
                for item in all_kvs:
                    if not isinstance(item, dict):
                        continue
                    if "field_id" in item:
                        key = str(item["field_id"])
                        value = dict(item)
                        value.pop("field_id", None)
                        normalized[key] = value
                    elif len(item) == 1:
                        k, v = next(iter(item.items()))
                        normalized[k] = v
                all_kvs = normalized
            elif not isinstance(all_kvs, dict):
                all_kvs = {}

            valid_urls = {
                str(e.get("url", "")).strip() for e in all_evidence if e.get("url")
            }
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

                # DEFECT 2 FIX: deterministic numeric value/content fidelity gate
                source_content = url_to_content.get(src, "")
                fact_value = str(value.get("value", ""))
                if not value_supported_by_source(fact_value, source_content):
                    print(f"[FACT REJECT] field={key} reason=value_not_in_evidence value={fact_value!r} source={src!r}")
                    continue

                validated[key] = value
            all_kvs = validated

            return (all_kvs, result)
        except Exception as e:
            print(f"[extract] fail: {e}")
            return ({}, {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})


class FakeLLM:
    def __init__(self, raw_content: str):
        self.raw_content = raw_content

    def analyze(self, system, prompt, temperature=0.1):
        return {
            "content": self.raw_content,
            "model": "test", "requested_model": "test",
            "tokens_input": 0, "tokens_output": 0, "api_cost": 0,
        }


def run_case(label, old_or_new, checker, all_evidence):
    print("=" * 90)
    print(f"{label} [{old_or_new}]")
    print("=" * 90)
    facts, _ = checker.extract_facts_batch(all_evidence, [])
    print(f"RESULT total={len(facts)} keys={list(facts.keys())}")
    for k, v in facts.items():
        print(f"  {k} = {v}")
    print()
    return facts


if __name__ == "__main__":
    # -----------------------------------------------------------------
    # DEFECT 1: single-element JSON array response -> total=0 bug
    # -----------------------------------------------------------------
    url_d1 = "https://example.com/d1"
    evidence_d1 = [{"url": url_d1, "content": "Diameter is 4-inch per spec sheet.", "doc_type": "spec_table"}]
    raw_d1 = (
        "Here are the facts I found:\n"
        "```json\n"
        f'[{{"field_id": "port_diameter", "value": "4-inch", "source": "{url_d1}", "source_type": "spec_table"}}]\n'
        "```\n"
    )

    old_checker_d1 = FactChecker(FakeLLM(raw_d1))
    facts_old_d1 = run_case("DEFECT 1 (single-element array, wrapped in prose/markdown)", "OLD/production", old_checker_d1, evidence_d1)
    assert len(facts_old_d1) == 0, f"expected OLD to reproduce total=0 bug, got {facts_old_d1}"
    print("[PASS] OLD reproduces the total=0 bug for a single-element array response.\n")

    cand_checker_d1 = CandidateFactChecker(FakeLLM(raw_d1))
    facts_new_d1 = run_case("DEFECT 1 (single-element array, wrapped in prose/markdown)", "CANDIDATE", cand_checker_d1, evidence_d1)
    assert "port_diameter" in facts_new_d1, f"expected CANDIDATE to recover port_diameter, got {facts_new_d1}"
    assert facts_new_d1["port_diameter"]["value"] == "4-inch"
    print("[PASS] CANDIDATE correctly recovers the fact from a single-element array response.\n")

    # -----------------------------------------------------------------
    # DEFECT 2: real production hallucination case (subenclosure.net /
    # ACR 12500 Black) -- fabricated 12-inch port dimensions never
    # present in the source content.
    # -----------------------------------------------------------------
    url_d2 = "https://subenclosure.net/port-formula"
    source_content_d2 = (
        "Standard formula: L = (23,562 x D^2) / (Fb^2 x Vb) - 0.732D. "
        "Example: 4-inch port, 35 Hz tuning, 1.5 cf net. "
        "Material: MDF. Port type: Slot."
    )
    evidence_d2 = [{"url": url_d2, "content": source_content_d2, "doc_type": "forum"}]

    raw_d2 = json.dumps({
        "port_diameter": {"value": "4-inch", "source": url_d2, "source_type": "forum"},
        "port_width": {"value": "12-inch", "source": url_d2, "source_type": "forum"},
        "port_height": {"value": "12-inch", "source": url_d2, "source_type": "forum"},
        "box_build_frequency": {"value": "35 Hz", "source": url_d2, "source_type": "forum"},
        "box_build_volume": {"value": "1.5 cf", "source": url_d2, "source_type": "forum"},
        "material": {"value": "MDF", "source": url_d2, "source_type": "forum"},
        "port_shape": {"value": "Slot", "source": url_d2, "source_type": "forum"},
    })

    old_checker_d2 = FactChecker(FakeLLM(raw_d2))
    facts_old_d2 = run_case("DEFECT 2 (subenclosure.net hallucination case)", "OLD/production", old_checker_d2, evidence_d2)
    assert "port_width" in facts_old_d2 and "port_height" in facts_old_d2, (
        "expected OLD to keep the fabricated 12-inch facts (proving the hallucination survives today)"
    )
    print("[PASS] OLD keeps the fabricated port_width/port_height=12-inch facts (hallucination confirmed).\n")

    cand_checker_d2 = CandidateFactChecker(FakeLLM(raw_d2))
    facts_new_d2 = run_case("DEFECT 2 (subenclosure.net hallucination case)", "CANDIDATE", cand_checker_d2, evidence_d2)
    assert "port_width" not in facts_new_d2, f"expected CANDIDATE to reject fabricated port_width, got {facts_new_d2}"
    assert "port_height" not in facts_new_d2, f"expected CANDIDATE to reject fabricated port_height, got {facts_new_d2}"
    assert facts_new_d2.get("port_diameter", {}).get("value") == "4-inch", "expected legitimate port_diameter to survive"
    assert facts_new_d2.get("material", {}).get("value") == "MDF", "expected non-numeric material fact to survive untouched"
    assert facts_new_d2.get("port_shape", {}).get("value") == "Slot", "expected non-numeric port_shape fact to survive untouched"
    # Explicitly out of scope for PATCH 1: example-vs-actual mislabeling.
    # These numeric values ARE present in the source text, so the fidelity
    # gate correctly does not touch them -- that's PATCH 2's job.
    assert facts_new_d2.get("box_build_frequency", {}).get("value") == "35 Hz", (
        "PATCH 1 must not remove the example-labeled 35 Hz value; that is PATCH 2 scope"
    )
    assert facts_new_d2.get("box_build_volume", {}).get("value") == "1.5 cf", (
        "PATCH 1 must not remove the example-labeled 1.5 cf value; that is PATCH 2 scope"
    )
    print("[PASS] CANDIDATE rejects fabricated 12-inch facts, keeps legitimate facts, and correctly")
    print("       leaves the example-vs-actual (35 Hz / 1.5 cf) question untouched for PATCH 2.\n")

    print("=" * 90)
    print("ALL PATCH 1 VERIFY CASES PASSED")
    print("=" * 90)

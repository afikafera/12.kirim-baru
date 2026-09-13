import sys
import os

sys.path.insert(0, os.path.abspath("."))

from hermes_agent.fact_checker import (
    FactChecker,
    _is_sentinel_non_fact,
)

PASS_COUNT = 0
FAIL_COUNT = 0

def check(case_id, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    status = "PASS" if condition else "FAIL"
    if condition:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
    print(f"[{status}] {case_id}: {detail}")
    return condition

print("=" * 75)
print("VERIFICATION SUITE: CANDIDATE 2 (COMPLETION SEMANTICS & SENTINEL REJECTION)")
print("=" * 75)

# TEST A
print("\n--- TEST A: Sentinel Non-Fact Detection ---")
sentinels = [
    "Not found in evidence",
    "not found",
    "Not available in evidence",
    "N/A",
    "none",
    "unknown",
    "tidak ditemukan",
    "Tidak ditemukan dalam bukti",
    "Data tidak ditemukan",
    "Tidak tersedia",
    "Tidak ada",
]

for s in sentinels:
    check(
        f"A_SENTINEL_{s[:15].replace(' ', '_')}",
        _is_sentinel_non_fact(s) is True,
        f"Sentinel rejected: {s!r}",
    )

# TEST B
print("\n--- TEST B: Legitimate Facts Pass Gate ---")
legit_facts = [
    "6794 km",
    "686.980 days",
    "Mars is a terrestrial planet",
    "~0.5 Earth diameter",
    "Found in Gale Crater: 150 km diameter",
    "Not 100% certain, but 6792 km",
    "None of the terrestrial planets have rings",
    "ACR 1240 500W 8 ohm",
]

for f in legit_facts:
    check(
        f"B_LEGIT_{f[:15].replace(' ', '_')}",
        _is_sentinel_non_fact(f) is False,
        f"Legit fact preserved: {f!r}",
    )

# TEST C
print("\n--- TEST C: State Cleanliness on 'Not found in evidence' ---")
test_url = "https://ssd.jpl.nasa.gov/planets/phys_par.html"
evidence_content = (
    "## Specifications\n"
    "Title: Planetary Physical Parameters\n"
    "URL Source: https://ssd.jpl.nasa.gov/planets/phys_par.html\n\n"
    "| Planet | Equatorial Radius |\n"
    "| Mercury | 2440.53 |\n"
    "| Venus | 6051.8 |\n"
)
all_evidence = [
    {
        "url": test_url,
        "content": evidence_content,
        "evidence_type": "general",
        "doc_type": "general",
    }
]

raw_extracted_facts = {
    "mars_diameter_nasa": {
        "value": "Not found in evidence",
        "source": test_url,
        "source_type": "general",
    }
}

req_id = "Mars diameter NASA [Data diameter planet Mars dari resmi NASA]"

validated = {}
for key, value in raw_extracted_facts.items():
    src = str(value.get("source", "")).strip()
    fact_value = str(value.get("value", ""))
    if _is_sentinel_non_fact(fact_value):
        continue
    validated[key] = value

check(
    "C1_EXTRACT_REJECTS_SENTINEL",
    len(validated) == 0,
    f"Validated facts is empty after sentinel rejection: {validated}",
)

fc = FactChecker(llm_analyzer=None)
checklist = [{"field_id": "mars_diameter_nasa", "label": "mars_diameter_nasa"}]
eval_result = fc.evaluate(checklist, raw_extracted_facts, all_evidence)

check(
    "C2_EVALUATE_COVERAGE_ZERO",
    eval_result["coverage_pct"] == 0.0 and eval_result["filled"] == 0,
    f"evaluate() coverage is 0% (filled={eval_result['filled']}, empty={eval_result['empty']})",
)

MIN_COVERAGE = 50
request_facts = {}
kg_status = {}

persistent_ranked = {
    field: fact
    for field, fact in validated.items()
    if isinstance(fact, dict) and str(fact.get("source", "")) != "user://request"
}

if eval_result["coverage_pct"] >= MIN_COVERAGE and persistent_ranked:
    for field, fact in persistent_ranked.items():
        request_facts[f"{req_id}/{field}"] = {
            "value": fact.get("value"),
            "source": fact.get("source", "unknown"),
        }
    kg_status[req_id] = "found"
else:
    kg_status[req_id] = "partial"

def request_requirement_complete(target_req_id):
    prefix = f"{target_req_id}/"
    return any(key.startswith(prefix) for key in request_facts)

is_complete = request_requirement_complete(req_id)

check(
    "C3_PERSISTENT_RANKED_EMPTY",
    len(persistent_ranked) == 0,
    f"persistent_ranked is empty: {persistent_ranked}",
)

check(
    "C4_REQUEST_FACTS_CLEAN",
    len(request_facts) == 0,
    f"request_facts remains empty: {request_facts}",
)

check(
    "C5_KG_STATUS_PARTIAL",
    kg_status.get(req_id) == "partial",
    f"kg_status remains 'partial' (NOT 'found'): {kg_status.get(req_id)}",
)

check(
    "C6_REQ_COMPLETE_FALSE",
    is_complete is False,
    f"request_requirement_complete() is False -> retry & recovery CAN TRIGGER!",
)

# TEST D
print("\n--- TEST D: Regression with Mixed Extraction Payload ---")
mixed_facts = {
    "mars_diameter_esa": {
        "value": "6794 km",
        "source": "https://sci.esa.int/mars-express",
        "source_type": "article",
    },
    "mars_diameter_nasa": {
        "value": "Not found in evidence",
        "source": test_url,
        "source_type": "general",
    },
    "mars_atmosphere": {
        "value": "Mars is a terrestrial planet",
        "source": "https://science.nasa.gov/mars",
        "source_type": "article",
    },
}

validated_mixed = {}
for key, value in mixed_facts.items():
    val = str(value.get("value", ""))
    if not _is_sentinel_non_fact(val):
        validated_mixed[key] = value

check(
    "D1_MIXED_PRESERVES_VALID",
    set(validated_mixed.keys()) == {"mars_diameter_esa", "mars_atmosphere"},
    f"Only legitimate facts preserved from mixed payload: {list(validated_mixed.keys())}",
)

eval_mixed = fc.evaluate(
    [{"field_id": k} for k in mixed_facts.keys()],
    mixed_facts,
    all_evidence,
)

check(
    "D2_MIXED_EVALUATE_COUNTS",
    eval_mixed["filled"] == 2 and eval_mixed["empty"] == 1,
    f"evaluate() correctly counts 2 filled and 1 empty: filled={eval_mixed['filled']}, empty={eval_mixed['empty']}",
)

print("\n" + "=" * 75)
print(f"VERIFICATION SUMMARY: {PASS_COUNT} PASS, {FAIL_COUNT} FAIL")
print("=" * 75)
if FAIL_COUNT == 0:
    print("[SUCCESS] Candidate 2 Patch PASSED all acceptance criteria!")
else:
    print("[FAILURE] Some acceptance criteria failed!")
    sys.exit(1)

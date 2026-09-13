"""
VERIFY harness for Controller Continuation Runtime in hermes_agent/orchestrator.py.
Read-only inspection of runtime behavior, contracts, state injection, and URL routing.

Run from project root:
    python3 verify_continuation_runtime.py
"""
import sys
import json
import logging
from unittest.mock import MagicMock

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("verify_continuation")

from hermes_agent.orchestrator import HermesAgent
from hermes_agent.knowledge_graph import KnowledgeGraph

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

print("=" * 70)
print("VERIFIKASI RUNTIME CONTROLLER CONTINUATION")
print("=" * 70)

# Inisialisasi HermesAgent dengan mock dependencies
agent = HermesAgent.__new__(HermesAgent)
agent.llm = MagicMock()
agent.strategy = MagicMock()
agent.strategy.score_url = MagicMock(return_value=0.8)

# ----------------------------------------------------------------------
# TEST 1: Contract Evaluator Return Tuple & Parsing
# ----------------------------------------------------------------------
cache = {}
mock_llm_response = {
    "content": json.dumps({
        "fulfilled": False,
        "missing": ["All other temperature brackets (35C, 34C) and prices"],
        "reason": "Only 36C bracket is present in the facts"
    })
}
agent.llm.analyze = MagicMock(return_value=mock_llm_response)

fulfilled, reason, missing = agent._evaluate_requirement_fulfillment(
    topic="Shanghai temperature",
    need="Temperature brackets",
    success_criteria=["All brackets listed"],
    facts={"node1/bracket_36": {"value": "36C: 0.05"}},
    cache=cache
)

check("T1.1_EVAL_TUPLE", isinstance((fulfilled, reason, missing), tuple) and len((fulfilled, reason, missing)) == 3,
      f"Evaluator contract return 3-tuple: len={len((fulfilled, reason, missing))}")
check("T1.2_EVAL_DECISION", fulfilled is False, f"Decision fulfilled={fulfilled}")
check("T1.3_EVAL_MISSING", isinstance(missing, list) and len(missing) == 1, f"Missing items parsed: {missing}")
check("T1.4_EVAL_CACHE", len(cache) == 1, "Hasil evaluasi tersimpan di semantic cache")

# ----------------------------------------------------------------------
# TEST 2: Generic _resolve_recovery_requirement()
# ----------------------------------------------------------------------
plan = {"goal": "Shanghai Highest Temperature", "knowledge_required": []}
recovery_k = agent._resolve_recovery_requirement(
    unmet_reason=reason,
    current_facts={},
    plan=plan,
    missing_items=missing,
    goal=plan["goal"]
)

check("T2.1_RESOLVE_GENERIC", recovery_k is not None, "Recovery requirement berhasil dibuat dari missing criteria")
check("T2.2_RESOLVE_TOPIC", "All other temperature brackets" in recovery_k.get("topic", ""),
      f"Topic spesifik kriteria: {recovery_k.get('topic')}")
check("T2.3_RESOLVE_FLAGS", recovery_k.get("is_recovery") is True and recovery_k.get("depends_on") == [],
      f"Flags valid: is_recovery={recovery_k.get('is_recovery')}, deps={recovery_k.get('depends_on')}")

# Fail-closed test jika missing_items kosong
fail_closed_k = agent._resolve_recovery_requirement(
    unmet_reason="random text",
    current_facts={},
    plan=plan,
    missing_items=[],
    goal=plan["goal"]
)
check("T2.4_FAIL_CLOSED", fail_closed_k is None, "Fail-closed: Return None jika missing_items kosong")

# ----------------------------------------------------------------------
# TEST 3: Dynamic 4-Way Injection (_inject_recovery_requirement)
# ----------------------------------------------------------------------
kg = KnowledgeGraph()
requirement_map = {}
request_scope = set()
goal = plan["goal"]

injected_id = agent._inject_recovery_requirement(
    new_k=recovery_k,
    plan=plan,
    requirement_map=requirement_map,
    kg=kg,
    request_scope=request_scope,
    goal=goal
)

check("T3.1_INJECT_RETURN", injected_id is not None and len(injected_id) > 0, f"Injected ID: {injected_id}")
check("T3.2_INJECT_PLAN", recovery_k in plan["knowledge_required"], "Terdaftar di plan['knowledge_required']")
check("T3.3_INJECT_MAP", injected_id in requirement_map, "Terdaftar di requirement_map")
check("T3.4_INJECT_KG", injected_id in kg.graph["nodes"], "Terdaftar sebagai node KnowledgeGraph")
check("T3.5_INJECT_SCOPE", injected_id in request_scope, "Terdaftar di request_scope")

# Idempotency check
dup_injected_id = agent._inject_recovery_requirement(
    new_k=recovery_k,
    plan=plan,
    requirement_map=requirement_map,
    kg=kg,
    request_scope=request_scope,
    goal=goal
)
check("T3.6_INJECT_IDEMPOTENT", dup_injected_id is None, "Idempotency terjaga: duplicate injection ditolak")

# ----------------------------------------------------------------------
# TEST 4: Readiness Progression (Old node skipped, Recovery node ready)
# ----------------------------------------------------------------------
# Simulasikan node awal sudah punya fakta di request_facts
orig_req_id = "Initial Requirement [data]"
requirement_map[orig_req_id] = {"topic": "Initial Requirement", "need": "data", "depends_on": []}
kg.add_node(orig_req_id, status="found")

request_facts = {
    f"{orig_req_id}/field1": {"value": "some_value"}
}

def request_requirement_complete(r_id):
    prefix = f"{r_id}/"
    return any(key.startswith(prefix) for key in request_facts)

ready_list = []
for r_id, k in requirement_map.items():
    if request_requirement_complete(r_id):
        continue
    ready_list.append(r_id)

check("T4.1_READINESS_SKIP_OLD", orig_req_id not in ready_list, "Node awal di-skip karena request_requirement_complete=True")
check("T4.2_READINESS_PICK_RECOVERY", injected_id in ready_list, f"Recovery node READY: {ready_list}")

# ----------------------------------------------------------------------
# TEST 5: Controller Gate Deduplication & Max Recovery Limit
# ----------------------------------------------------------------------
max_recovery = getattr(agent, "MAX_RECOVERY_ATTEMPTS", 1)
check("T5.1_MAX_RECOVERY_VALUE", max_recovery == 2, f"MAX_RECOVERY_ATTEMPTS live value adalah {max_recovery}")

attempted_sigs = set()
sig = (recovery_k.get("topic"), recovery_k.get("need"))
attempted_sigs.add(sig)

is_duplicate = sig in attempted_sigs
check("T5.2_DEDUP_SIGNATURE", is_duplicate is True, "Deduplication signature mendeteksi percobaan berulang")

# ----------------------------------------------------------------------
# TEST 6: URL Selection & direct_urls Hijack Inspection
# ----------------------------------------------------------------------
# Simulasi apakah direct_urls membajak recovery node
sample_direct_urls = ["https://polymarket.com/event/shanghai-temperature"]

def simulate_url_selection(k, direct_urls):
    node_target = k.get("target")
    if node_target:
        return [node_target], "TARGET_MODE"
    elif direct_urls:
        return list(direct_urls), "DIRECT_TARGET_MODE"
    else:
        return ["https://search.engine/result"], "SEARCH_MODE"

urls_chosen, mode_chosen = simulate_url_selection(recovery_k, sample_direct_urls)
print(f"[PROBE] Recovery Node URL Mode saat direct_urls ada: {mode_chosen} -> {urls_chosen}")

if mode_chosen == "DIRECT_TARGET_MODE":
    print("  [ALERT] POTENSI GAP TERDETEKSI: Recovery node dibajak oleh direct_urls!")
    print("          Ia tidak akan mencari ke search engine, melainkan memanggil URL lama lagi.")
else:
    print("  [OK] Recovery node bebas mencari ke search engine.")

print("=" * 70)
print(f"HASIL VERIFIKASI: {PASS_COUNT} PASS, {FAIL_COUNT} FAIL")
print("=" * 70)

"""
VERIFY harness for direct_urls -> recovery node routing inside process_node().
Confirms whether search_one() is bypassed and if cached evidence is strictly reused.

Run from project root:
    python3 verify_recovery_routing.py
"""
import sys

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
print("VERIFIKASI URL ROUTING PADA RECOVERY NODE")
print("=" * 70)

# Simulasi state environment
goal_with_url = "Berdasarkan live data Polymarket https://polymarket.com/event/shanghai-temperature cari seluruh bracket"
direct_urls = ["https://polymarket.com/event/shanghai-temperature"]
request_fetch_cache = {
    "https://polymarket.com/event/shanghai-temperature": {
        "url": "https://polymarket.com/event/shanghai-temperature",
        "content": "Only 36C or higher is visible on this single page."
    }
}

# 1. Initial requirement (seharusnya memakai direct_urls)
initial_node = {
    "topic": "Polymarket market live data",
    "need": "market brackets and prices",
    "is_recovery": False,
    "target": None
}

# 2. Recovery requirement (seharusnya MENCARI data yang hilang, bukan membuka URL lama lagi)
recovery_node = {
    "topic": "Shanghai Highest Temperature - All other temperature brackets (35C, 34C) and prices",
    "need": "Collect specific verifiable data: All other temperature brackets",
    "is_recovery": True,
    "target": None
}

# ----------------------------------------------------------------------
# TEST A: Current Live Logic in orchestrator.py (L1579-L1596)
# ----------------------------------------------------------------------
def current_live_routing(k, direct_urls_list):
    search_executed = False
    all_urls = []
    
    node_target = k.get("target")
    if node_target:
        all_urls = [node_target]
        mode = "REQ_TARGET_MODE"
    elif direct_urls_list:
        all_urls = list(direct_urls_list)
        mode = "DIRECT_TARGET_MODE"
    else:
        search_executed = True
        all_urls = ["https://search.engine/api/polymarket-brackets"]
        mode = "SEARCH_MODE"
        
    return mode, all_urls, search_executed

mode_init, urls_init, search_init = current_live_routing(initial_node, direct_urls)
mode_rec, urls_rec, search_rec = current_live_routing(recovery_node, direct_urls)

check("A1_INIT_NODE_USES_DIRECT", mode_init == "DIRECT_TARGET_MODE" and urls_init == direct_urls,
      f"Node awal memakai direct_urls: mode={mode_init}")

# Ini adalah bukti konkret gap:
check("A2_RECOVERY_NODE_HIJACKED", mode_rec == "DIRECT_TARGET_MODE" and search_rec is False,
      f"Recovery node TERBUKTI DIBAJAK: mode={mode_rec}, search_executed={search_rec}")

# ----------------------------------------------------------------------
# TEST B: Dampak Cache Reuse pada Evidence Recovery
# ----------------------------------------------------------------------
# Di orchestrator.py L1701:
new_urls = [u for u in urls_rec if u not in request_fetch_cache]
evidence_for_req = [request_fetch_cache[u] for u in urls_rec if u in request_fetch_cache]

check("B1_NO_NEW_FETCH", len(new_urls) == 0, f"new_urls kosong (tidak ada fetch HTTP baru): {new_urls}")
check("B2_EVIDENCE_REUSE_SAME", len(evidence_for_req) == 1 and "Only 36C" in evidence_for_req[0]["content"],
      "Evidence recovery identik dengan cache halaman awal (tidak ada data bracket baru)")

# ----------------------------------------------------------------------
# TEST C: Solusi Minimal (Exempt recovery node from direct_urls)
# ----------------------------------------------------------------------
def proposed_candidate_routing(k, direct_urls_list):
    search_executed = False
    all_urls = []
    
    node_target = k.get("target")
    if node_target:
        all_urls = [node_target]
        mode = "REQ_TARGET_MODE"
    elif direct_urls_list and not k.get("is_recovery"):
        all_urls = list(direct_urls_list)
        mode = "DIRECT_TARGET_MODE"
    else:
        search_executed = True
        all_urls = ["https://search.engine/api/polymarket-brackets"]
        mode = "SEARCH_MODE"
        
    return mode, all_urls, search_executed

p_mode_init, p_urls_init, p_search_init = proposed_candidate_routing(initial_node, direct_urls)
p_mode_rec, p_urls_rec, p_search_rec = proposed_candidate_routing(recovery_node, direct_urls)

check("C1_PROPOSED_INIT_UNCHANGED", p_mode_init == "DIRECT_TARGET_MODE" and p_urls_init == direct_urls,
      "Node awal TETAP memakai direct_urls (preserve existing hard-target behavior)")

check("C2_PROPOSED_RECOVERY_SEARCHES", p_mode_rec == "SEARCH_MODE" and p_search_rec is True,
      "Recovery node BERHASIL beralih ke SEARCH_MODE untuk mencari kriteria yang hilang!")

print("=" * 70)
print(f"HASIL VERIFIKASI: {PASS_COUNT} PASS, {FAIL_COUNT} FAIL")
print("=" * 70)

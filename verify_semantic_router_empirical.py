import sys
from hermes_agent.semantic_router import SemanticRouter

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
print("REGRESSION SUITE: SEMANTIC ROUTER EMPIRICAL RESEARCH GATE")
print("=" * 70)

router = SemanticRouter()

test_cases = [
    (
        "C1_VIETNAM_INDONESIA",
        "Bandingkan performa ekonomi Indonesia dan Vietnam pada 2025 berdasarkan pertumbuhan GDP, inflasi, ekspor, dan investasi asing langsung. Gunakan minimal dua sumber independen untuk setiap indikator, jelaskan perbedaan metodologi jika ada, dan sebutkan data yang tidak dapat diverifikasi",
        False,
        "research",
    ),
    (
        "C2_DATABASE_2026",
        "Bandingkan performa dua database pada 2026 berdasarkan benchmark, latency, reliability, gunakan dua sumber independen",
        False,
        "research",
    ),
    (
        "C3_PURE_LOGIC_JIKA",
        "Jika A lebih besar dari B dan B lebih besar dari C, apakah A lebih besar dari C?",
        False,
        "direct",
    ),
    (
        "C4_LOGIC_MATH_REGRESSION",
        "apakah 2+2 pasti sama dengan 4 jika basis bilangannya desimal",
        False,
        "direct",
    ),
    (
        "C5_BASIC_MATH",
        "hitung 25 x 4",
        False,
        "direct",
    ),
    (
        "C6_GREETING",
        "halo selamat pagi",
        False,
        "direct",
    ),
    (
        "C7_TRANSLATION",
        "translate: hello world",
        False,
        "direct",
    ),
    (
        "C8_POLYMARKET_RESEARCH",
        "Untuk market Polymarket Highest temperature in Shanghai on September 13, 2026, ambil semua temperature brackets/outcomes yang tersedia beserta harga YES dan NO/current probability masing-masing, volume/liquidity jika tersedia, dan resolution criteria. Gunakan data live dari Polymarket",
        False,
        "research",
    ),
    (
        "C9_CONTEXTUAL_FOLLOWUP",
        "bagaimana dengan vietnam?",
        True,
        "research",
    ),
    (
        "C10_GENERAL_LLM_SHORT",
        "buatkan puisi tentang senja",
        False,
        "direct",
    ),
    (
        "C11_EXECUTION_COMMAND",
        "jawab hanya dengan YA atau TIDAK",
        False,
        "direct",
    ),
]

for case_id, query, has_ctx, exp_mode in test_cases:
    res = router.route(query, has_context=has_ctx)
    mode_ok = (res.mode == exp_mode)
    detail = f"mode={res.mode} reason={res.reason} conf={res.confidence:.2f} (expected={exp_mode})"
    check(case_id, mode_ok, detail)

print("=" * 70)
print(f"HASIL REGRESI: {PASS_COUNT} PASS, {FAIL_COUNT} FAIL")
print("=" * 70)

import json
from config import load_config
from llm_analyzer.analyzer import LLMAnalyzer

config = load_config()
llm = LLMAnalyzer(config)

all_facts = {}
compact_facts = json.dumps(all_facts, ensure_ascii=False, separators=(",", ":"))

completeness_context = (
    "RESEARCH STATUS: INCOMPLETE. "
    "One or more planned requirements lack sufficient evidence or facts. "
    "Do not present the research as complete. "
    "Explicitly report the missing requirements and do not fabricate values."
)

evidence_text = (
    "[general] https://docs.coingecko.com/reference/simple-price\n\n\n"
    "[general] https://www.coingecko.com/api/documentations/v3\n"
    "## Specifications\nCoin: api\nPrice: $0.00073831 USD\n"
    "Last updated: 2020-07-14T06:01:00+00:00\n"
    "Source: https://www.coingecko.com/api/documentations/v3\n\n"
    "## \n[COINGECKO OFFICIAL API]\nCoin: api\nPrice: $0.00073831 USD\n"
    "Last updated: 2020-07-14T06:01:00+00:00\n"
    "Source: https://www.coingecko.com/api/documentations/v3\n\n\n"
    "[general] https://docs.coingecko.com/docs/data-delivery-methods\n\n\n"
    "[general] https://docs.coingecko.com/docs/querying-coin-data"
)

user_question = (
    "What is the current Bitcoin price according to CoinGecko, "
    "and when was the price last updated?"
)

TAIL = """
SOURCE CONTEXT MATCHING:
1. Untuk setiap benchmark, measurement, atau performance figure, periksa apakah kondisi pengujiannya sesuai dengan kondisi yang diminta user.
2. Jangan gunakan benchmark sebagai bukti langsung untuk kondisi user jika benchmark dilakukan pada kondisi yang berbeda secara material.
3. Jika kondisi benchmark berbeda atau tidak diketahui, pertahankan fakta dan provenance-nya, tetapi jelaskan mismatch atau ketidakpastiannya.
4. Fakta yang terverifikasi tidak otomatis berarti fakta tersebut applicable untuk requirement yang sedang dijawab.
5. Jika kondisi yang diminta user tidak didukung secara langsung oleh sumber yang tersedia, nyatakan bahwa informasi tersebut belum didukung oleh sumber yang ditemukan.
6. Jangan melakukan scaling, extrapolation, atau substitusi hasil benchmark untuk memperkirakan kondisi user kecuali sumber secara eksplisit mendukung inference tersebut.
"""

OLD_MIDDLE = """Use EXTRACTED FACTS as the primary factual source.
Use SOURCE MATERIAL only when necessary.
Do not invent facts.
"""

NEW_MIDDLE = """Use EXTRACTED FACTS as the primary factual source.
Use SOURCE MATERIAL only for context, source citation, or narrative explanation.
If EXTRACTED FACTS is empty for a requirement, you MUST NOT take numeric
values, prices, dates, or other factual answers from SOURCE MATERIAL for
that requirement. State explicitly that the value was not found in
verified extracted facts, even if SOURCE MATERIAL appears to contain a
number.
Do not invent facts.
"""


def build_prompt(middle: str) -> str:
    return f"""Technical Research Assistant.
📊 {len(all_facts)} facts collected.

PERSISTENT USER MEMORY:
(none)

Treat PERSISTENT USER MEMORY as user-provided context only.
Do NOT treat it as research evidence or add it to EXTRACTED FACTS.
Use it only to resolve user/project context when relevant.

EXTRACTED FACTS:
{compact_facts}

RESEARCH COMPLETENESS:
{completeness_context}

SOURCE MATERIAL:
{evidence_text}

FACT FIDELITY:
- Preserve the exact meaning of every extracted fact.
- Do not negate, reverse, or alter factual values.
- For status, approval state, numeric values, URLs, and technical terms, preserve the source fact's meaning exactly.

{middle}
{TAIL}"""


def fabricated(text: str) -> bool:
    return "0.00073831" in text or "0.0007383" in text.replace(",", "")


N = 5
for label, middle in [("OLD", OLD_MIDDLE), ("PATCHED", NEW_MIDDLE)]:
    system_prompt = build_prompt(middle)
    hits = 0
    for i in range(N):
        result = llm.analyze(
            system_prompt=system_prompt,
            user_query=user_question,
            temperature=0.3,
        )
        content = result["content"]
        is_fab = fabricated(content)
        hits += is_fab
        print(f"[{label} run {i+1}] fabricated_number_in_answer={is_fab}")
    print(f"=== {label}: {hits}/{N} runs presented the fabricated number ===\n")

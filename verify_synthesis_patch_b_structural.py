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

evidence_text_redacted = (
    "[general] https://docs.coingecko.com/reference/simple-price "
    "(content withheld: no verified facts extracted from this source)\n\n"
    "[general] https://www.coingecko.com/api/documentations/v3 "
    "(content withheld: no verified facts extracted from this source)\n\n"
    "[general] https://docs.coingecko.com/docs/data-delivery-methods "
    "(content withheld: no verified facts extracted from this source)\n\n"
    "[general] https://docs.coingecko.com/docs/querying-coin-data "
    "(content withheld: no verified facts extracted from this source)"
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

MIDDLE = """Use EXTRACTED FACTS as the primary factual source.
Use SOURCE MATERIAL only for context, source citation, or narrative explanation.
If EXTRACTED FACTS is empty for a requirement, you MUST NOT take numeric
values, prices, dates, or other factual answers from SOURCE MATERIAL for
that requirement. State explicitly that the value was not found in
verified extracted facts, even if SOURCE MATERIAL appears to contain a
number.
Do not invent facts.
"""


def build_prompt(evidence_text: str) -> str:
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

{MIDDLE}
{TAIL}"""


system_prompt = build_prompt(evidence_text_redacted)
N = 5
for i in range(N):
    result = llm.analyze(
        system_prompt=system_prompt,
        user_query=user_question,
        temperature=0.3,
    )
    print("=" * 80)
    print(f"STRUCTURAL-REDACTED run {i+1}")
    print("=" * 80)
    print(result["content"])
    print()

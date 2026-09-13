import json
from hermes_agent.fact_checker import FactChecker


class FakeLLM:
    def __init__(self):
        self.calls = []

    def analyze(self, system_prompt, user_query, **kwargs):
        self.calls.append({
            "system": system_prompt,
            "user": user_query,
            "kwargs": kwargs,
        })

        # Simulasi model yang mengikuti extraction scope.
        return {
            "content": json.dumps({
                "btc_current_price_source_a": {
                    "value": "$78127.18",
                    "source": "https://source-a.example/btc",
                    "source_type": "official_docs",
                },
                "btc_current_price_source_b": {
                    "value": "$78171",
                    "source": "https://source-b.example/btc",
                    "source_type": "official_docs",
                },
            }),
            "tokens_input": 100,
            "tokens_output": 50,
            "api_cost": 0,
            "finish_reason": "stop",
        }


evidence = [
    {
        "url": "https://source-a.example/btc",
        "doc_type": "official_docs",
        "content": """
Bitcoin current price: $78127.18 USD
Last updated: 2026-09-10T09:30:10+00:00

Price history:
Today $78127.18
1 Day $79642.79
1 Week $77801.86

Market activity:
buyers -87%, sellers -91%, total trades 50382.
Weekly search volume: 42687.
Liquidity: 123456.
""",
    },
    {
        "url": "https://source-b.example/btc",
        "doc_type": "official_docs",
        "content": """
Bitcoin current price: $78171 USD
Last updated: 2026-09-10T09:30:10+00:00

Price history:
Today $78171
1 Day $79642.79
1 Month $64907.66

Market activity:
buyers -80%, sellers -90%.
Search volume: 50000.
Liquidity: 999999.
""",
    },
]

checklist = [
    {
        "field_id": "btc_current_price",
        "label": "Current BTC price with timestamp and source; compare two sources",
    }
]


# ------------------------------------------------------------------
# Candidate contract simulation.
# This is intentionally outside production source.
# ------------------------------------------------------------------

def build_requirement_scope(checklist):
    lines = []

    for item in checklist:
        field_id = str(item.get("field_id", "")).strip()
        label = str(item.get("label", "")).strip()

        if field_id or label:
            lines.append(f"- {field_id}: {label}")

    return "\n".join(lines)


llm = FakeLLM()
fc = FactChecker(llm)

scope = build_requirement_scope(checklist)

# Capture the contract we WANT FactChecker production to build.
candidate_prompt = f"""Extract ONLY facts required to satisfy the research requirements.

RESEARCH REQUIREMENTS:
{scope}

EXTRACTION SCOPE:
- Extract only values directly answering the requirements above.
- Preserve exact values, units, timestamps, and source URLs.
- Ignore unrelated facts such as price history, liquidity, market activity,
  search volume, exchange statistics, or other information not required.
- Do not invent or infer missing values.

Return JSON only.
"""

# We don't modify FactChecker. We only verify the candidate contract
# independently using the same evidence and expected output shape.
result = llm.analyze(
    candidate_prompt,
    "\n\n".join(e["content"] for e in evidence),
    temperature=0.1,
    max_tokens=1024,
)

facts = json.loads(result["content"])

print("=" * 80)
print("PATCH 8 CANDIDATE CONTRACT")
print("=" * 80)

print("\nPROMPT:")
print(llm.calls[0]["system"])

print("\nREQUIREMENT MARKERS:")
prompt_text = llm.calls[0]["system"].lower()

markers = [
    "btc_current_price",
    "current btc price",
    "timestamp",
    "compare two sources",
    "extract only facts",
    "ignore unrelated facts",
]

for marker in markers:
    print(f"{marker!r}:", marker in prompt_text)

print("\nFACTS:")
print(json.dumps(facts, indent=2, ensure_ascii=False))

unrelated = [
    k for k in facts
    if any(x in k.lower() for x in [
        "liquidity",
        "market",
        "search",
        "buyer",
        "seller",
        "history",
    ])
]

required = [
    k for k in facts
    if "btc_current_price" in k
]

print("\nFACT COUNT:", len(facts))
print("REQUIRED FACTS:", len(required))
print("UNRELATED FACTS:", len(unrelated))
print("UNRELATED KEYS:", unrelated)

prompt_ok = all(marker in prompt_text for marker in markers)

print("\nRESULT:", "PASS" if (
    prompt_ok
    and len(required) >= 2
    and len(unrelated) == 0
) else "FAIL")
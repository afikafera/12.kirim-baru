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

        # Candidate expectation:
        # requirement harus terlihat di prompt.
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

llm = FakeLLM()
fc = FactChecker(llm)

facts, result = fc.extract_facts_batch(evidence, checklist)

print("=" * 80)
print("HARNESS RESULT")
print("=" * 80)

print("LLM_CALLS:", len(llm.calls))

for i, call in enumerate(llm.calls, 1):
    print(f"\n--- CALL {i} SYSTEM ---")
    print(call["system"])
    print(f"\n--- CALL {i} USER ---")
    print(call["user"])

prompt_text = "\n".join(
    call["system"] + "\n" + call["user"]
    for call in llm.calls
)

required_markers = [
    "btc_current_price",
    "Current BTC price",
    "timestamp",
    "compare two sources",
]

print("\nPROMPT REQUIREMENT MARKERS:")
for marker in required_markers:
    print(f"{marker!r}:", marker.lower() in prompt_text.lower())

print("\nFACTS:")
print(json.dumps(facts, indent=2, ensure_ascii=False))

print("\nFACT COUNT:", len(facts))
print("UNRELATED LIQUIDITY FACTS:",
      sum("liquidity" in k.lower() for k in facts))
print("UNRELATED MARKET FACTS:",
      sum(
          any(x in k.lower() for x in ["market", "search", "buyer", "seller"])
          for k in facts
      ))

print("\nRESULT:", "PASS" if (
    llm.calls
    and all(marker.lower() in prompt_text.lower() for marker in required_markers)
    and len(facts) == 2
    and sum("liquidity" in k.lower() for k in facts) == 0
    and sum(
        any(x in k.lower() for x in ["market", "search", "buyer", "seller"])
        for k in facts
    ) == 0
) else "FAIL")
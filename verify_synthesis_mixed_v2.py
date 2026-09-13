from pathlib import Path

src = Path("hermes_agent/orchestrator.py").read_text()

old = """        synthesis_evidence = [e for e in all_evidence if e.get("had_facts")]
        if not synthesis_evidence:
            synthesis_evidence = all_evidence
"""

print("=== SOURCE BLOCK PRESENT (double-quote match) ===")
print(old in src)


def build_synthesis_evidence(all_evidence):
    synthesis_evidence = [e for e in all_evidence if e.get("had_facts")]
    if not synthesis_evidence:
        synthesis_evidence = [
            {**e, "content": "[content withheld: no verified facts extracted from this source]"}
            for e in all_evidence
        ]
    return synthesis_evidence


def render(synthesis_evidence, cap=4):
    return "\n\n".join([
        f"[{e.get('doc_type','?')}] {e['url']}\n{e['content'][:400]}"
        for e in synthesis_evidence[:cap]
    ])


print("\n=== CASE A: mixed (1 has_facts=True, 1 has_facts=False) ===")
case_a = [
    {
        "url": "https://valid.example",
        "doc_type": "general",
        "content": "VALID FACT: Bitcoin price is $79,553.95 USD.",
        "had_facts": True,
    },
    {
        "url": "https://unverified.example",
        "doc_type": "general",
        "content": "UNVERIFIED: Bitcoin price is $0.00073831 USD.",
        "had_facts": False,
    },
]
se_a = build_synthesis_evidence(case_a)
text_a = render(se_a)
print("synthesis_evidence entries:", len(se_a))
print("rendered evidence_text:")
print(text_a)
print("PASS (no leak, valid entry present):",
      "$0.00073831" not in text_a and "$79,553.95" in text_a)

print("\n=== CASE B: zero facts anywhere (fallback path) ===")
case_b = [
    {
        "url": "https://unverified1.example",
        "doc_type": "general",
        "content": "UNVERIFIED: Bitcoin price is $0.00073831 USD.",
        "had_facts": False,
    },
    {
        "url": "https://unverified2.example",
        "doc_type": "general",
        "content": "Coin: api, Price: $0.00073831 USD",
        "had_facts": False,
    },
]
se_b = build_synthesis_evidence(case_b)
text_b = render(se_b)
print("synthesis_evidence entries:", len(se_b))
print("rendered evidence_text:")
print(text_b)
print("PASS (no leak, URLs still cited for transparency):",
      "$0.00073831" not in text_b
      and "https://unverified1.example" in text_b
      and "https://unverified2.example" in text_b)

print("\n=== CASE C: all have facts (sanity, unchanged behavior) ===")
case_c = [
    {"url": f"https://ok{i}.example", "doc_type": "general",
     "content": f"Fact content {i}", "had_facts": True}
    for i in range(6)
]
se_c = build_synthesis_evidence(case_c)
text_c = render(se_c)
print("synthesis_evidence entries (should be 6, capped display at 4):", len(se_c))
print("rendered evidence_text:")
print(text_c)
print("PASS (unchanged filter+cap behavior, no redaction):",
      len(se_c) == 6 and "[content withheld" not in text_c
      and text_c.count("Fact content") == 4)

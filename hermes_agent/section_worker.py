"""
Execution worker for one Hermes Output Scaling section.

The worker prepares a deterministic section-scoped prompt and performs
exactly one LLMAnalyzer call. It does not retry, route, recover,
split, continue, assemble, or decide job completion.
"""

import json
import re
from typing import Any, Dict, Optional

from hermes_agent.output_manifest import OutputSection


def is_comparison_section(section: OutputSection) -> bool:
    """Deterministically detect if a section scope involves comparative analysis."""
    corpus = f"{section.title} {section.intent} {section.expected_shape}"
    return bool(
        re.search(
            r"\b(vs|versus|perbandingan|bandingkan|komparasi|compare|comparison|trade-?offs?)\b",
            corpus,
            re.IGNORECASE,
        )
    )


def is_recommendation_section(section: OutputSection) -> bool:
    """Deterministically detect if a section scope involves recommendations or decisions."""
    corpus = f"{section.title} {section.intent} {section.expected_shape}"
    return bool(
        re.search(
            r"\b(rekomendasi|recommendation|recommend|kesimpulan|conclusion|saran|action\s+plan)\b",
            corpus,
            re.IGNORECASE,
        )
    )


UNIVERSAL_GUARDRAILS = """FACT FIDELITY:
- Preserve the exact meaning of every extracted fact.
- Do not negate, reverse, or alter factual values or status.
- For numeric values, dates, URLs, and technical terms, preserve the source fact's meaning exactly.
- Do not invent facts or extrapolate beyond EXTRACTED FACTS.

SOURCE CONTEXT MATCHING:
- Check whether testing, benchmark, or measurement conditions match user-requested conditions.
- Do not scale, extrapolate, or substitute benchmark/performance figures across materially different test environments without explicit source support.
- If benchmark conditions differ or are unknown, state the mismatch and uncertainty explicitly rather than asserting direct equivalence.

SOURCE SCOPE PRESERVATION & ASYMMETRY PROTECTION:
- Missing facts in research indicate an information gap, NOT negative evidence.
- Do not treat the absence of facts as evidence that an entity or method is worse, slower, more expensive, or less secure.
- If Entity A has facts but Entity B lacks facts, do NOT conclude that Entity A is superior overall.
- If EXTRACTED FACTS do not support a required item, explicitly state that evidence is insufficient for that item."""

COMPARISON_CONTRACT = """COMPARISON-FIRST REASONING:
1. Do not choose a winner or make a final selection upfront.
2. Identify comparison criteria before drawing conclusions.
3. For each criterion, compare only facts with comparable context and test conditions.
4. If sources for an entity are missing for a criterion, state that sources were not found; do not fill gaps with general knowledge.
5. After comparison, separate what is directly supported by evidence, what is incomparable, and what is limited inference.
6. Do not declare an overall winner if sources only support superiority on a subset of criteria."""

RECOMMENDATION_CONTRACT = """RECOMMENDATION & DECISION CONTRACT:
1. Recommendations must strictly follow comparison and verified evidence, not pre-conceived preference.
2. Recommend only when supported by comparable source facts.
3. Structure recommendations transparently:
   - Summary of findings supported by facts.
   - Information gaps and unverified criteria.
   - Conclusion strictly bounded by evidence.
   - Conditional recommendation (or advise empirical testing if evidence is inconclusive).
4. If the available evidence is insufficient to choose a definitive option, state explicitly that sources are insufficient rather than forcing a recommendation."""


class SectionWorker:
    """Execute one output section through the existing LLMAnalyzer."""

    def __init__(self, llm):
        self.llm = llm

    def build_system_prompt(
        self,
        section: OutputSection,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        context = context or {}

        facts = context.get("all_facts", {})
        evidence = context.get("synthesis_evidence", [])
        completeness = context.get("completeness_context", "")
        memory = context.get("memory_context", "")
        requirement_audit = context.get("requirement_audit", [])

        facts_text = json.dumps(
            facts,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        evidence_text = json.dumps(
            evidence,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        audit_text = json.dumps(
            requirement_audit,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        must_cover_text = "\n".join(
            f"- {item}" for item in section.must_cover
        ) or "- No explicit checklist supplied."

        prompt_parts = [
            f"""Technical Research Assistant — Section Worker.

SECTION ID:
{section.section_id}

REQUIREMENT ID:
{section.requirement_id}

SECTION TITLE:
{section.title}

SECTION INTENT:
{section.intent}

REQUIRED COVERAGE:
{must_cover_text}

EXPECTED OUTPUT SHAPE:
{section.expected_shape}

RESEARCH COMPLETENESS:
{completeness or "(not supplied)"}

EXTRACTED FACTS:
{facts_text}

SOURCE MATERIAL:
{evidence_text}

REQUIREMENT AUDIT:
{audit_text}

PERSISTENT USER MEMORY:
{memory or "(none)"}

RULES:
1. Answer only the scope of this section.
2. Cover every item in REQUIRED COVERAGE when supported by the supplied evidence.
3. Use EXTRACTED FACTS as the primary factual source.
4. Preserve factual meaning, numeric values, URLs, status, and technical terms.
5. Do not invent facts.
6. If supplied evidence does not support a required item, explicitly state that
   the source/evidence is insufficient for that item.
7. Do not treat PERSISTENT USER MEMORY as research evidence.
8. Do not answer unrelated sections or add unrelated deliverables.
9. Follow EXPECTED OUTPUT SHAPE.
10. Produce only the section content, without meta-commentary about this worker.

{UNIVERSAL_GUARDRAILS}"""
        ]

        if is_comparison_section(section):
            prompt_parts.append(f"\n{COMPARISON_CONTRACT}")

        if is_recommendation_section(section):
            prompt_parts.append(f"\n{RECOMMENDATION_CONTRACT}")

        return "\n".join(prompt_parts) + "\n"

    def build_user_query(
        self,
        section: OutputSection,
        goal: str = "",
    ) -> str:
        return (
            f"Research goal:\n{goal}\n\n"
            f"Write section {section.section_id}: {section.title}.\n"
            f"Section intent: {section.intent}\n"
        )

    def execute(
        self,
        section: OutputSection,
        *,
        goal: str = "",
        context: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.3,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute exactly one LLM call for one section.

        Any exception from LLMAnalyzer is intentionally propagated to the
        caller, which owns recovery/provider-failure policy.
        """
        system_prompt = self.build_system_prompt(
            section,
            context=context,
        )

        user_query = self.build_user_query(
            section,
            goal=goal,
        )

        return self.llm.analyze(
            system_prompt=system_prompt,
            user_query=user_query,
            temperature=temperature,
            model=model,
            max_tokens=max_tokens,
        )

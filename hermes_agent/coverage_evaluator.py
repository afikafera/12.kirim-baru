from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CoverageResult:
    covered_items: list[str]
    remaining_items: list[str]
    semantic_complete: bool | None
    reason: str


class CoverageEvaluator:
    """
    Evaluates whether an output section substantively covers its
    declared coverage targets.

    This component does not establish factual truth. Factual truth
    remains bounded by the supplied evidence/facts layer.
    """

    def __init__(self, llm=None):
        self.llm = llm

    def evaluate(
        self,
        section: Any,
        accumulated_text: str,
        facts: dict | None = None,
    ) -> CoverageResult:
        must_cover = list(getattr(section, "must_cover", []) or [])

        if not must_cover:
            return CoverageResult(
                covered_items=[],
                remaining_items=[],
                semantic_complete=True,
                reason="no_coverage_targets",
            )

        if not accumulated_text or not accumulated_text.strip():
            return CoverageResult(
                covered_items=[],
                remaining_items=list(must_cover),
                semantic_complete=False,
                reason="empty_output",
            )

        if self.llm is None:
            return CoverageResult(
                covered_items=[],
                remaining_items=list(must_cover),
                semantic_complete=None,
                reason="evaluator_unavailable",
            )

        result = self._evaluate_with_llm(
            must_cover=must_cover,
            accumulated_text=accumulated_text,
            facts=facts or {},
        )

        return self._normalize_result(result, must_cover)

    def _evaluate_with_llm(
        self,
        must_cover: list[str],
        accumulated_text: str,
        facts: dict,
    ) -> dict:
        import json

        prompt = f"""You are a strict output coverage evaluator.

COVERAGE TARGETS:
{json.dumps(must_cover, ensure_ascii=False)}

OUTPUT SECTION:
{accumulated_text}

SUPPLIED FACTS / EVIDENCE CONTEXT:
{json.dumps(facts, ensure_ascii=False, default=str)}

TASK:
Determine which declared coverage targets are substantively addressed
by the output section.

Rules:
- Evaluate only the supplied output and evidence context.
- Do not use general knowledge.
- Do not invent missing information.
- Do not treat the existence of a fact as proof that the output covers it.
- A target is covered only when the output substantively addresses it.
- Do not create new coverage targets.
- Preserve the target wording exactly in covered/remaining lists.
- Every target must appear in exactly one of covered or remaining.

Return ONLY valid JSON:
{{"covered": [], "remaining": [], "semantic_complete": true_or_false, "reason": "short reason"}}
"""

        result = self.llm.analyze(
            system_prompt=(
                "You are a strict output coverage evaluator. "
                "Use only supplied output and evidence context. "
                "Never invent missing information."
            ),
            user_query=prompt,
            temperature=0.0,
        )

        return result if isinstance(result, dict) else {}

    @staticmethod
    def _normalize_result(
        result: dict,
        must_cover: list[str],
    ) -> CoverageResult:
        covered_raw = result.get("covered", [])
        remaining_raw = result.get("remaining", [])

        if not isinstance(covered_raw, list):
            covered_raw = []

        if not isinstance(remaining_raw, list):
            remaining_raw = []

        covered = [
            item for item in must_cover
            if item in {str(x).strip() for x in covered_raw if str(x).strip()}
        ]

        covered_set = set(covered)

        remaining = [
            item for item in must_cover
            if item not in covered_set
        ]

        semantic_complete = result.get("semantic_complete")
        if not isinstance(semantic_complete, bool):
            semantic_complete = None

        if semantic_complete is True and remaining:
            semantic_complete = False

        if semantic_complete is False and not remaining:
            semantic_complete = True

        reason = str(result.get("reason") or "coverage_evaluated").strip()

        return CoverageResult(
            covered_items=covered,
            remaining_items=remaining,
            semantic_complete=semantic_complete,
            reason=reason,
        )

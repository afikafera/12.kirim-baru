from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from hermes_agent.coverage_evaluator import CoverageResult
from hermes_agent.output_manifest import (
    OutcomeType,
    OutputSection,
    SectionRuntimeState,
)


class ContinuationDecision(str, Enum):
    CONTINUE = "CONTINUE"
    SPLIT = "SPLIT"
    FINALIZE = "FINALIZE"
    DEGRADE = "DEGRADE"
    FAIL = "FAIL"


@dataclass(frozen=True)
class ContinuationPolicyResult:
    decision: ContinuationDecision
    reason: str


class ContinuationPolicy:
    """
    Deterministic policy for deciding what happens after one section
    execution.

    This policy does not execute, route, retry, split, or persist work.
    It only returns a decision from explicit runtime state and signals.
    """

    @staticmethod
    def decide(
        section: OutputSection,
        state: SectionRuntimeState,
        outcome: OutcomeType,
        coverage: Optional[CoverageResult] = None,
    ) -> ContinuationPolicyResult:

        remaining = (
            list(coverage.remaining_items)
            if coverage is not None
            else list(state.remaining_items)
        )

        if outcome == OutcomeType.COMPLETE:
            if remaining:
                if state.continuation_count < section.max_continuations:
                    return ContinuationPolicyResult(
                        ContinuationDecision.CONTINUE,
                        "complete_signal_but_coverage_remaining",
                    )

                if len(remaining) > 1:
                    return ContinuationPolicyResult(
                        ContinuationDecision.SPLIT,
                        "continuation_budget_exhausted_with_multiple_remaining_items",
                    )

                return ContinuationPolicyResult(
                    ContinuationDecision.DEGRADE,
                    "continuation_budget_exhausted_with_remaining_coverage",
                )

            return ContinuationPolicyResult(
                ContinuationDecision.FINALIZE,
                "complete_and_coverage_satisfied",
            )

        if outcome in (
            OutcomeType.TRUNCATED,
            OutcomeType.SEMANTICALLY_INCOMPLETE,
        ):
            if not remaining:
                return ContinuationPolicyResult(
                    ContinuationDecision.FINALIZE,
                    "incomplete_signal_but_no_coverage_remaining",
                )

            if state.continuation_count < section.max_continuations:
                return ContinuationPolicyResult(
                    ContinuationDecision.CONTINUE,
                    "coverage_remaining_and_continuation_budget_available",
                )

            if len(remaining) > 1:
                return ContinuationPolicyResult(
                    ContinuationDecision.SPLIT,
                    "continuation_budget_exhausted_with_multiple_remaining_items",
                )

            return ContinuationPolicyResult(
                ContinuationDecision.DEGRADE,
                "continuation_budget_exhausted_with_remaining_coverage",
            )

        if outcome == OutcomeType.NO_PROGRESS:
            return ContinuationPolicyResult(
                ContinuationDecision.DEGRADE,
                "no_progress",
            )

        if outcome == OutcomeType.PROVIDER_FAILURE:
            return ContinuationPolicyResult(
                ContinuationDecision.DEGRADE,
                "provider_failure",
            )

        if outcome == OutcomeType.STRUCTURALLY_INVALID:
            return ContinuationPolicyResult(
                ContinuationDecision.DEGRADE,
                "structurally_invalid_output",
            )

        return ContinuationPolicyResult(
            ContinuationDecision.FAIL,
            f"unsupported_outcome:{outcome}",
        )

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

    MAX_PROVIDER_RETRIES = 1

    @staticmethod
    def decide(
        section: OutputSection,
        state: SectionRuntimeState,
        outcome: OutcomeType,
        coverage: Optional[CoverageResult] = None,
        *,
        multi_model_router: bool = False,
        failure_subtype: Optional[str] = None,
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

        if outcome == OutcomeType.SEMANTICALLY_INCOMPLETE:
            if not remaining:
                return ContinuationPolicyResult(
                    ContinuationDecision.FINALIZE,
                    "incomplete_signal_but_no_coverage_remaining",
                )

            return ContinuationPolicyResult(
                ContinuationDecision.DEGRADE,
                "semantic_coverage_remaining",
            )

        if outcome == OutcomeType.TRUNCATED:
            if state.continuation_count < section.max_continuations:
                return ContinuationPolicyResult(
                    ContinuationDecision.CONTINUE,
                    "truncated_continuation_budget_available",
                )

            return ContinuationPolicyResult(
                ContinuationDecision.DEGRADE,
                "truncated_continuation_budget_exhausted",
            )

        if outcome == OutcomeType.NO_PROGRESS:
            return ContinuationPolicyResult(
                ContinuationDecision.DEGRADE,
                "no_progress",
            )

        retryable_subtypes = {
            "transient_unavailable",
            "timeout/network",
            "null_output",
            "unknown_provider_error",
        }
        deterministic_subtypes = {
            "context_length_exceeded",
            "tpm_or_request_size_rejected",
            "unsupported/deprecated",
        }
        if outcome == OutcomeType.PROVIDER_FAILURE:
            if (
                multi_model_router
                and failure_subtype not in deterministic_subtypes
                and failure_subtype in retryable_subtypes
                and state.provider_retry_count < ContinuationPolicy.MAX_PROVIDER_RETRIES
            ):
                return ContinuationPolicyResult(
                    ContinuationDecision.CONTINUE,
                    f"retry_same_section_after_{failure_subtype}",
                )
            if multi_model_router and failure_subtype in deterministic_subtypes:
                reason = f"provider_failure_not_retried_{failure_subtype}"
            else:
                reason = (
                    "provider_failure_retry_exhausted"
                    if multi_model_router
                    else "provider_failure_single_model"
                )
            return ContinuationPolicyResult(
                ContinuationDecision.DEGRADE,
                reason,
            )

        if outcome == OutcomeType.STRUCTURALLY_INVALID:
            if (
                multi_model_router
                and failure_subtype == "null_output"
                and state.provider_retry_count < ContinuationPolicy.MAX_PROVIDER_RETRIES
            ):
                return ContinuationPolicyResult(
                    ContinuationDecision.CONTINUE,
                    "retry_same_section_after_null_output",
                )
            return ContinuationPolicyResult(
                ContinuationDecision.DEGRADE,
                "structurally_invalid_output",
            )

        return ContinuationPolicyResult(
            ContinuationDecision.FAIL,
            f"unsupported_outcome:{outcome}",
        )

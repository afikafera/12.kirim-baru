"""
One-step continuation engine for ARAN Output Scaling.

Boundary:
    Worker       = execution
    Store        = state persistence
    Classifier   = execution signal
    Coverage     = semantic output coverage
    Policy       = continuation decision
    Engine       = one execution cycle

The engine performs at most one worker execution per step.
It does not retry, route providers, schedule sections, split sections,
or assemble the final response.
"""

from dataclasses import dataclass
import json
import logging
from typing import Any, Optional

from hermes_agent.continuation_policy import ContinuationPolicy
from hermes_agent.llm_output_contract import llm_output_failure
from hermes_agent.output_manifest import OutcomeType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContinuationStepResult:
    """Result of exactly one continuation execution cycle."""

    outcome: OutcomeType
    coverage: Any
    policy: Any
    state: Any
    failure_subtype: Optional[str] = None
    failure_detail: Optional[str] = None
    provider_retry_count_before: int = 0
    provider_retry_count_after: int = 0


class ContinuationEngine:
    """Execute exactly one section-generation/continuation step."""

    def __init__(
        self,
        *,
        worker,
        store,
        outcome_classifier,
        coverage_evaluator,
        continuation_policy=None,
        multi_model_router: bool = False,
        request_id: str = "",
    ):
        self.worker = worker
        self.store = store
        self.outcome_classifier = outcome_classifier
        self.coverage_evaluator = coverage_evaluator
        self.continuation_policy = (
            continuation_policy
            or ContinuationPolicy()
        )
        self.multi_model_router = bool(multi_model_router)
        self.request_id = str(request_id or "")

    def step(
        self,
        section,
        *,
        goal: str = "",
        facts=None,
        evidence=None,
        context=None,
        requirement_audit=None,
        memory=None,
        temperature: float = 0.3,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> ContinuationStepResult:
        """
        Execute exactly one worker call and evaluate the resulting state.

        No retry or continuation loop is performed here.
        """

        state = self.store.get(section.section_id)
        retry_count_before = state.provider_retry_count
        requested_model = self._requested_model(model)
        previous_remaining = (
            frozenset(state.remaining_items)
            if state.chunks and state.remaining_items
            else None
        )

        execution_context = dict(context or {})

        if facts is not None:
            execution_context["all_facts"] = facts

        if evidence is not None:
            execution_context["synthesis_evidence"] = evidence

        if requirement_audit is not None:
            execution_context["requirement_audit"] = requirement_audit

        if memory is not None:
            execution_context["memory_context"] = memory

        execution_context.update(
            {
                "goal": goal,
                "accumulated_text": state.accumulated_text,
                "remaining_items": list(
                    state.remaining_items
                    if state.chunks
                    else (state.remaining_items or section.must_cover)
                ),
                "continuation_count": state.continuation_count,
                "section_id": section.section_id,
                "continuation": bool(state.chunks),
            }
        )

        self.store.update_metadata(
            section.section_id,
            attempts_total=state.attempts_total + 1,
        )

        try:
            result = self.worker.execute(
                section,
                goal=goal,
                context=execution_context,
                temperature=temperature,
                model=model,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            outcome = self.outcome_classifier.classify(exception=exc)
            failure_subtype = self.outcome_classifier.failure_subtype(exception=exc)
            failure_detail = f"{type(exc).__name__}: {str(exc)[:300]}"
            self.store.update_metadata(
                section.section_id,
                last_outcome=outcome,
                last_failure_subtype=failure_subtype,
            )
            current_state = self.store.get(section.section_id)
            coverage = self._evaluate_coverage(section, current_state, facts)
            policy = self.continuation_policy.decide(
                section,
                current_state,
                outcome,
                coverage,
                multi_model_router=self.multi_model_router,
                failure_subtype=failure_subtype,
            )
            if policy.decision.value == "CONTINUE":
                self.store.update_metadata(
                    section.section_id,
                    provider_retry_count=current_state.provider_retry_count + 1,
                )
            final_state = self.store.get(section.section_id)
            self._log_attempt(
                section, outcome, policy, final_state,
                retry_count_before, failure_subtype, failure_detail, requested_model,
            )
            return ContinuationStepResult(
                outcome=outcome,
                coverage=coverage,
                policy=policy,
                state=final_state,
                failure_subtype=failure_subtype,
                failure_detail=failure_detail,
                provider_retry_count_before=retry_count_before,
                provider_retry_count_after=final_state.provider_retry_count,
            )

        if not isinstance(result, dict):
            failure = True
            content = None
        else:
            content = result.get("content")
            failure = (
                content is None
                or not isinstance(content, str)
                or not content.strip()
            )

        if not failure:
            self.store.append_chunk(
                section.section_id,
                content,
            )

        tokens_output = (
            result.get("tokens_output", 0)
            if isinstance(result, dict)
            else 0
        )

        current_state = self.store.get(section.section_id)

        self.store.update_metadata(
            section.section_id,
            budget_used_tokens=(
                current_state.budget_used_tokens
                + int(tokens_output or 0)
            ),
            last_model=(
                result.get("model")
                if isinstance(result, dict)
                else None
            ),
            last_finish_reason=(
                result.get("finish_reason")
                if isinstance(result, dict)
                else None
            ),
            last_tokens_output=int(tokens_output or 0),
        )

        current_state = self.store.get(section.section_id)

        coverage = self._evaluate_coverage(
            section,
            current_state,
            facts,
        )

        semantic_complete = (
            coverage.semantic_complete
            if coverage is not None
            else None
        )

        no_progress = (
            previous_remaining is not None
            and coverage is not None
            and llm_output_failure(result) is None
            and previous_remaining == frozenset(coverage.remaining_items)
        )

        outcome = self.outcome_classifier.classify(
            result,
            semantic_complete=semantic_complete,
            no_progress=no_progress,
        )
        failure_subtype = self.outcome_classifier.failure_subtype(result)
        failure_detail = llm_output_failure(result)

        self.store.update_metadata(
            section.section_id,
            last_outcome=outcome,
            last_failure_subtype=failure_subtype,
        )

        if coverage is not None:
            current_state = self.store.get(section.section_id)
            current_state.remaining_items = list(
                coverage.remaining_items
            )
            current_state.covered_items = list(
                coverage.covered_items
            )
            self.store.put(current_state)

        current_state = self.store.get(section.section_id)

        policy = self.continuation_policy.decide(
            section,
            current_state,
            outcome,
            coverage,
            multi_model_router=self.multi_model_router,
            failure_subtype=failure_subtype,
        )

        if policy.decision.value == "CONTINUE":
            if failure_subtype == "null_output":
                self.store.update_metadata(
                    section.section_id,
                    provider_retry_count=current_state.provider_retry_count + 1,
                )
            else:
                self.store.update_metadata(
                    section.section_id,
                    continuation_count=current_state.continuation_count + 1,
                )

        final_state = self.store.get(section.section_id)
        self._log_attempt(
            section, outcome, policy, final_state,
            retry_count_before, failure_subtype, failure_detail, requested_model,
        )
        return ContinuationStepResult(
            outcome=outcome,
            coverage=coverage,
            policy=policy,
            state=final_state,
            failure_subtype=failure_subtype,
            failure_detail=failure_detail,
            provider_retry_count_before=retry_count_before,
            provider_retry_count_after=final_state.provider_retry_count,
        )

    def _requested_model(self, model):
        if model is not None:
            return str(model)
        analyzer = getattr(self.worker, "llm", None)
        getter = getattr(analyzer, "get_requested_model", None)
        if callable(getter):
            return getter()
        return getattr(analyzer, "default_model", None)

    def _log_attempt(
        self, section, outcome, policy, state, retry_before,
        failure_subtype, failure_detail, requested_model,
    ):
        payload = {
            "request_id": self.request_id,
            "section_id": section.section_id,
            "requirement_id": section.requirement_id,
            "requested_model_alias": requested_model,
            "multi_model_router": self.multi_model_router,
            "provider_retry_count_before": retry_before,
            "classification": outcome.value,
            "failure_subtype": failure_subtype,
            "failure_detail": failure_detail,
            "policy_decision": policy.decision.value,
            "policy_reason": policy.reason,
            "provider_retry_count_after": state.provider_retry_count,
            "section_store_state": {
                "status": state.status.value,
                "attempts_total": state.attempts_total,
                "continuation_count": state.continuation_count,
                "provider_retry_count": state.provider_retry_count,
                "last_model": state.last_model,
                "last_outcome": (
                    state.last_outcome.value if state.last_outcome else None
                ),
                "last_failure_subtype": state.last_failure_subtype,
                "chunk_count": len(state.chunks),
                "accumulated_chars": len(state.accumulated_text),
                "remaining_items": list(state.remaining_items),
            },
            "final_section_status": None,
        }
        logger.info(
            "[CONTINUATION ATTEMPT] %s",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )

    def _evaluate_coverage(self, section, state, facts):
        if self.coverage_evaluator is None:
            return None

        return self.coverage_evaluator.evaluate(
            section,
            state.accumulated_text,
            facts=facts,
        )

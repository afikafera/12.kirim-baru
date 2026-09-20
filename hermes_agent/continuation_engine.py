"""
One-step continuation engine for Hermes Output Scaling.

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
from typing import Any, Optional

from hermes_agent.continuation_policy import ContinuationPolicy
from hermes_agent.output_manifest import OutcomeType


@dataclass(frozen=True)
class ContinuationStepResult:
    """Result of exactly one continuation execution cycle."""

    outcome: OutcomeType
    coverage: Any
    policy: Any
    state: Any


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
    ):
        self.worker = worker
        self.store = store
        self.outcome_classifier = outcome_classifier
        self.coverage_evaluator = coverage_evaluator
        self.continuation_policy = (
            continuation_policy
            or ContinuationPolicy()
        )

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
                    or section.must_cover
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
            outcome = self.outcome_classifier.classify(
                exception=exc,
            )

            self.store.update_metadata(
                section.section_id,
                last_outcome=outcome,
            )

            current_state = self.store.get(section.section_id)

            coverage = self._evaluate_coverage(
                section,
                current_state,
                facts,
            )

            policy = self.continuation_policy.decide(
                section,
                current_state,
                outcome,
                coverage,
            )

            return ContinuationStepResult(
                outcome=outcome,
                coverage=coverage,
                policy=policy,
                state=self.store.get(section.section_id),
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

        outcome = self.outcome_classifier.classify(
            result,
            semantic_complete=semantic_complete,
        )

        self.store.update_metadata(
            section.section_id,
            last_outcome=outcome,
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
        )

        if policy.decision.value == "CONTINUE":
            self.store.update_metadata(
                section.section_id,
                continuation_count=(
                    current_state.continuation_count + 1
                ),
            )

        return ContinuationStepResult(
            outcome=outcome,
            coverage=coverage,
            policy=policy,
            state=self.store.get(section.section_id),
        )

    def _evaluate_coverage(self, section, state, facts):
        if self.coverage_evaluator is None:
            return None

        return self.coverage_evaluator.evaluate(
            section,
            state.accumulated_text,
            facts=facts,
        )

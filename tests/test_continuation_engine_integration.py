import unittest

from hermes_agent.continuation_engine import ContinuationEngine
from hermes_agent.continuation_policy import (
    ContinuationDecision,
    ContinuationPolicy,
)
from hermes_agent.coverage_evaluator import CoverageEvaluator
from hermes_agent.output_manifest import (
    OutcomeType,
    OutputSection,
    SectionRuntimeState,
)
from hermes_agent.outcome_classifier import OutcomeClassifier
from hermes_agent.section_store import SectionStore
from hermes_agent.section_worker import SectionWorker


class FakeLLMAnalyzer:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def analyze(
        self,
        *,
        system_prompt,
        user_query,
        temperature=0.3,
        model=None,
        max_tokens=None,
    ):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_query": user_query,
            "temperature": temperature,
            "model": model,
            "max_tokens": max_tokens,
        })

        if self.error is not None:
            raise self.error

        return dict(self.result)


class FakeCoverageEvaluator:
    """
    Semantic evaluator boundary is isolated here.
    The real CoverageEvaluator is tested separately.
    """

    def __init__(self, remaining):
        self.remaining = list(remaining)
        self.calls = []

    def evaluate(self, section, accumulated_text, facts=None):
        self.calls.append({
            "section": section,
            "accumulated_text": accumulated_text,
            "facts": facts,
        })

        covered = [
            item
            for item in section.must_cover
            if item not in self.remaining
        ]

        return type(
            "Coverage",
            (),
            {
                "covered_items": covered,
                "remaining_items": list(self.remaining),
                "semantic_complete": not self.remaining,
                "reason": "integration-test",
            },
        )()


class ContinuationEngineIntegrationTests(unittest.TestCase):

    def section(self):
        return OutputSection(
            section_id="S001",
            requirement_id="R001",
            title="Output Scaling",
            intent="Describe output scaling",
            must_cover=[
                "token budget",
                "continuation",
            ],
            max_continuations=2,
        )

    def store(self):
        store = SectionStore()
        store.put(
            SectionRuntimeState(
                section_id="S001",
                remaining_items=[
                    "token budget",
                    "continuation",
                ],
            )
        )
        return store

    def test_real_worker_store_classifier_policy_pipeline(self):
        llm = FakeLLMAnalyzer({
            "content": "token budget",
            "model": "test-model",
            "requested_model": "test-provider",
            "finish_reason": "stop",
            "tokens_input": 10,
            "tokens_output": 20,
            "api_cost": 0.1,
        })

        worker = SectionWorker(llm)
        store = self.store()

        coverage = FakeCoverageEvaluator(
            remaining=["continuation"]
        )

        engine = ContinuationEngine(
            worker=worker,
            store=store,
            outcome_classifier=OutcomeClassifier(),
            coverage_evaluator=coverage,
            continuation_policy=ContinuationPolicy(),
        )

        result = engine.step(
            self.section(),
            goal="test output scaling",
            facts={"token budget": "supported"},
            max_tokens=128,
            model="test-provider",
        )

        self.assertEqual(
            len(llm.calls),
            1,
        )

        self.assertEqual(
            result.outcome,
            OutcomeType.SEMANTICALLY_INCOMPLETE,
        )

        self.assertEqual(
            result.policy.decision,
            ContinuationDecision.CONTINUE,
        )

        state = store.get("S001")

        self.assertEqual(
            state.accumulated_text,
            "token budget",
        )

        self.assertEqual(
            state.remaining_items,
            ["continuation"],
        )

        self.assertEqual(
            state.covered_items,
            ["token budget"],
        )

        self.assertEqual(
            state.attempts_total,
            1,
        )

        self.assertEqual(
            state.continuation_count,
            1,
        )

        self.assertEqual(
            state.last_model,
            "test-model",
        )

        self.assertEqual(
            state.last_finish_reason,
            "stop",
        )

        self.assertEqual(
            state.last_tokens_output,
            20,
        )

    def test_real_worker_preserves_truncation_signal(self):
        llm = FakeLLMAnalyzer({
            "content": "partial token",
            "model": "test-model",
            "requested_model": "test-provider",
            "finish_reason": "length",
            "tokens_input": 10,
            "tokens_output": 128,
            "api_cost": 0.1,
        })

        worker = SectionWorker(llm)
        store = self.store()

        coverage = FakeCoverageEvaluator(
            remaining=[
                "continuation",
            ]
        )

        engine = ContinuationEngine(
            worker=worker,
            store=store,
            outcome_classifier=OutcomeClassifier(),
            coverage_evaluator=coverage,
            continuation_policy=ContinuationPolicy(),
        )

        result = engine.step(
            self.section(),
            goal="test truncation",
            max_tokens=128,
        )

        self.assertEqual(
            result.outcome,
            OutcomeType.TRUNCATED,
        )

        self.assertEqual(
            result.policy.decision,
            ContinuationDecision.CONTINUE,
        )

        self.assertEqual(
            store.get("S001").accumulated_text,
            "partial token",
        )

    def test_real_worker_exception_reaches_real_classifier(self):
        error = RuntimeError("provider unavailable")

        llm = FakeLLMAnalyzer(
            error=error,
        )

        worker = SectionWorker(llm)
        store = self.store()

        coverage = FakeCoverageEvaluator(
            remaining=[
                "token budget",
                "continuation",
            ]
        )

        engine = ContinuationEngine(
            worker=worker,
            store=store,
            outcome_classifier=OutcomeClassifier(),
            coverage_evaluator=coverage,
            continuation_policy=ContinuationPolicy(),
        )

        result = engine.step(
            self.section(),
            goal="provider failure",
        )

        self.assertEqual(
            result.outcome,
            OutcomeType.PROVIDER_FAILURE,
        )

        self.assertEqual(
            result.policy.decision,
            ContinuationDecision.DEGRADE,
        )

        state = store.get("S001")

        self.assertEqual(
            state.accumulated_text,
            "",
        )

        self.assertEqual(
            state.attempts_total,
            1,
        )

        self.assertEqual(
            len(llm.calls),
            1,
        )


if __name__ == "__main__":
    unittest.main()

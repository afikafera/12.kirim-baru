import unittest
from types import SimpleNamespace

from hermes_agent.continuation_engine import (
    ContinuationEngine,
    ContinuationStepResult,
)
from hermes_agent.output_manifest import (
    OutputSection,
    SectionRuntimeState,
)
from hermes_agent.output_manifest import OutcomeType
from hermes_agent.continuation_policy import ContinuationDecision


class FakeWorker:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def execute(
        self,
        section,
        *,
        goal="",
        context=None,
        max_tokens=None,
        temperature=0.3,
        model=None,
    ):
        self.calls.append({
            "section": section,
            "goal": goal,
            "context": context,
            "model": model,
            "max_tokens": max_tokens,
        })
        if self.error:
            raise self.error
        return self.result


class FakeStore:
    def __init__(self, state):
        self.state = state
        self.chunks = []
        self.metadata = {}

    def get(self, section_id):
        return self.state

    def append_chunk(self, section_id, chunk):
        self.chunks.append(chunk)
        self.state.chunks.append(chunk)
        self.state.accumulated_text = "".join(self.state.chunks)
        return self.state

    def update_metadata(self, section_id, **kwargs):
        self.metadata.update(kwargs)

        for key, value in kwargs.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)

        return self.state

    def put(self, state):
        self.state = state


class FakeClassifier:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def classify(
        self,
        result=None,
        *,
        exception=None,
        semantic_complete=None,
        no_progress=False,
    ):
        self.calls.append({
            "result": result,
            "exception": exception,
            "semantic_complete": semantic_complete,
            "no_progress": no_progress,
        })
        return self.outcome


class FakeCoverage:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def evaluate(self, section, accumulated_text, facts=None):
        self.calls.append(
            (section, accumulated_text, facts)
        )
        return self.result


class FakePolicy:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def decide(self, section, state, outcome, coverage):
        self.calls.append(
            (section, state, outcome, coverage)
        )
        return self.result


class ContinuationEngineTests(unittest.TestCase):

    def section(self):
        return OutputSection(
            section_id="S001",
            requirement_id="R001",
            title="Test",
            intent="Test intent",
            must_cover=["item A", "item B"],
            max_continuations=2,
        )

    def state(self):
        return SectionRuntimeState(
            section_id="S001",
            remaining_items=["item B"],
        )

    def test_one_step_executes_worker_once_and_persists(self):
        worker = FakeWorker({
            "content": "item A",
            "model": "model-x",
            "requested_model": "provider-x",
            "finish_reason": "stop",
            "tokens_input": 10,
            "tokens_output": 20,
            "api_cost": 0.1,
        })

        store = FakeStore(self.state())

        classifier = FakeClassifier(
            OutcomeType.COMPLETE
        )

        coverage = FakeCoverage(
            SimpleNamespace(
                covered_items=["item A"],
                remaining_items=["item B"],
                semantic_complete=False,
                reason="remaining",
            )
        )

        policy = FakePolicy(
            SimpleNamespace(
                decision=ContinuationDecision.CONTINUE,
                reason="remaining",
            )
        )

        engine = ContinuationEngine(
            worker=worker,
            store=store,
            outcome_classifier=classifier,
            coverage_evaluator=coverage,
            continuation_policy=policy,
        )

        result = engine.step(
            self.section(),
            goal="test goal",
            context={"x": "y"},
            max_tokens=100,
            model="provider-x",
        )

        self.assertIsInstance(
            result,
            ContinuationStepResult,
        )
        self.assertEqual(len(worker.calls), 1)
        self.assertEqual(
            worker.calls[0]["goal"],
            "test goal",
        )
        self.assertEqual(
            store.chunks,
            ["item A"],
        )
        self.assertEqual(
            store.state.accumulated_text,
            "item A",
        )
        self.assertEqual(
            store.metadata["last_model"],
            "model-x",
        )
        self.assertEqual(
            store.metadata["last_finish_reason"],
            "stop",
        )
        self.assertEqual(
            store.metadata["last_tokens_output"],
            20,
        )
        self.assertEqual(
            result.policy.decision,
            ContinuationDecision.CONTINUE,
        )

    def test_no_second_worker_call_inside_one_step(self):
        worker = FakeWorker({
            "content": "partial",
            "model": "m",
            "requested_model": "p",
            "finish_reason": "length",
            "tokens_input": 1,
            "tokens_output": 2,
        })

        store = FakeStore(self.state())

        classifier = FakeClassifier(
            OutcomeType.TRUNCATED
        )

        coverage = FakeCoverage(
            SimpleNamespace(
                covered_items=["item A"],
                remaining_items=["item B"],
                semantic_complete=False,
                reason="truncated",
            )
        )

        policy = FakePolicy(
            SimpleNamespace(
                decision=ContinuationDecision.CONTINUE,
                reason="continue",
            )
        )

        engine = ContinuationEngine(
            worker=worker,
            store=store,
            outcome_classifier=classifier,
            coverage_evaluator=coverage,
            continuation_policy=policy,
        )

        engine.step(
            self.section(),
            goal="goal",
        )

        self.assertEqual(
            len(worker.calls),
            1,
        )

    def test_worker_exception_becomes_provider_failure_signal(self):
        error = RuntimeError("provider down")

        worker = FakeWorker(
            error=error,
        )

        store = FakeStore(self.state())

        classifier = FakeClassifier(
            OutcomeType.PROVIDER_FAILURE
        )

        coverage = FakeCoverage(
            SimpleNamespace(
                covered_items=[],
                remaining_items=[
                    "item A",
                    "item B",
                ],
                semantic_complete=None,
                reason="not evaluated",
            )
        )

        policy = FakePolicy(
            SimpleNamespace(
                decision=ContinuationDecision.DEGRADE,
                reason="provider failure",
            )
        )

        engine = ContinuationEngine(
            worker=worker,
            store=store,
            outcome_classifier=classifier,
            coverage_evaluator=coverage,
            continuation_policy=policy,
        )

        result = engine.step(
            self.section(),
            goal="goal",
        )

        self.assertEqual(
            result.outcome,
            OutcomeType.PROVIDER_FAILURE,
        )

        self.assertEqual(
            result.policy.decision,
            ContinuationDecision.DEGRADE,
        )

        self.assertEqual(
            store.chunks,
            [],
        )

        self.assertEqual(
            classifier.calls[0]["exception"],
            error,
        )

    def test_empty_content_is_not_persisted(self):
        worker = FakeWorker({
            "content": "",
            "model": "m",
            "requested_model": "p",
            "finish_reason": "stop",
            "tokens_input": 1,
            "tokens_output": 0,
        })

        store = FakeStore(self.state())

        classifier = FakeClassifier(
            OutcomeType.STRUCTURALLY_INVALID
        )

        coverage = FakeCoverage(
            SimpleNamespace(
                covered_items=[],
                remaining_items=[
                    "item A",
                    "item B",
                ],
                semantic_complete=None,
                reason="empty",
            )
        )

        policy = FakePolicy(
            SimpleNamespace(
                decision=ContinuationDecision.DEGRADE,
                reason="invalid",
            )
        )

        engine = ContinuationEngine(
            worker=worker,
            store=store,
            outcome_classifier=classifier,
            coverage_evaluator=coverage,
            continuation_policy=policy,
        )

        result = engine.step(
            self.section(),
            goal="goal",
        )

        self.assertEqual(
            result.outcome,
            OutcomeType.STRUCTURALLY_INVALID,
        )

        self.assertEqual(
            store.chunks,
            [],
        )

        self.assertEqual(
            len(worker.calls),
            1,
        )


if __name__ == "__main__":
    unittest.main()

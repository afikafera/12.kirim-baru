import json
import logging
import unittest

from hermes_agent.continuation_engine import ContinuationEngine
from hermes_agent.continuation_policy import ContinuationDecision, ContinuationPolicy
from hermes_agent.outcome_classifier import OutcomeClassifier
from hermes_agent.output_manifest import OutputSection, SectionRuntimeState, SectionStatus, OutcomeType
from hermes_agent.section_store import SectionStore


class ScriptedWorker:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def execute(self, section, **kwargs):
        self.calls.append((section, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class CompleteCoverage:
    def evaluate(self, section, accumulated_text, facts=None):
        remaining = [] if accumulated_text else list(section.must_cover)
        return type("Coverage", (), {
            "covered_items": list(section.must_cover) if accumulated_text else [],
            "remaining_items": remaining,
            "semantic_complete": bool(accumulated_text),
            "reason": "complete" if accumulated_text else "empty",
        })()


class FailureSubtypeRetryTests(unittest.TestCase):
    def setUp(self):
        self.section = OutputSection(
            section_id="S004",
            requirement_id="req_http_500_definition",
            title="HTTP 500",
            intent="Definition",
            must_cover=["HTTP 500 meaning"],
        )
        self.store = SectionStore()
        self.store.put(SectionRuntimeState(
            section_id=self.section.section_id,
            remaining_items=list(self.section.must_cover),
        ))
        self.classifier = OutcomeClassifier()

    def engine(self, outcomes, *, router=True):
        worker = ScriptedWorker(outcomes)
        engine = ContinuationEngine(
            worker=worker,
            store=self.store,
            outcome_classifier=self.classifier,
            coverage_evaluator=CompleteCoverage(),
            continuation_policy=ContinuationPolicy(),
            multi_model_router=router,
            request_id="req-observe-1",
        )
        return engine, worker

    def run_attempt(self, engine):
        return engine.step(self.section, model="9routerpc" if engine.multi_model_router else "deepseek-chat")

    def test_router_transient_unavailable_retries_same_section(self):
        engine, worker = self.engine([
            RuntimeError("Upstream request failed: Model is unavailable."),
            {"content": "HTTP 500 is a server error.", "model": "upstream-B"},
        ])
        first = self.run_attempt(engine)
        second = self.run_attempt(engine)
        self.assertEqual(first.failure_subtype, "transient_unavailable")
        self.assertEqual(first.policy.decision, ContinuationDecision.CONTINUE)
        self.assertEqual(first.provider_retry_count_after, 1)
        self.assertEqual(second.policy.decision, ContinuationDecision.FINALIZE)
        self.assertEqual([call[0].section_id for call in worker.calls], ["S004", "S004"])
        self.assertEqual([call[0].requirement_id for call in worker.calls], ["req_http_500_definition"] * 2)
        self.assertIs(worker.calls[0][0], worker.calls[1][0])

    def test_router_null_output_retries_same_section(self):
        engine, worker = self.engine([
            {"content": None, "model": "upstream-A"},
            {"content": "HTTP 500 is a server error.", "model": "upstream-B"},
        ])
        first = self.run_attempt(engine)
        second = self.run_attempt(engine)
        self.assertEqual(first.failure_subtype, "null_output")
        self.assertEqual(first.outcome, OutcomeType.STRUCTURALLY_INVALID)
        self.assertEqual(first.policy.decision, ContinuationDecision.CONTINUE)
        self.assertEqual(first.provider_retry_count_after, 1)
        self.assertEqual(second.policy.decision, ContinuationDecision.FINALIZE)
        self.assertEqual([call[0].section_id for call in worker.calls], ["S004", "S004"])

    def test_router_413_is_distinct_and_not_retried(self):
        exc = RuntimeError("413 Request too large for tokens per minute (TPM) limit")
        self.assertEqual(self.classifier.failure_subtype(exception=exc), "tpm_or_request_size_rejected")
        engine, worker = self.engine([exc])
        result = self.run_attempt(engine)
        self.assertEqual(result.outcome, OutcomeType.PROVIDER_FAILURE)
        self.assertEqual(result.policy.decision, ContinuationDecision.DEGRADE)
        self.assertEqual(result.policy.reason, "provider_failure_not_retried_tpm_or_request_size_rejected")
        self.assertEqual(len(worker.calls), 1)
        self.assertEqual(self.store.get("S004").provider_retry_count, 0)

    def test_context_length_error_is_distinct_and_not_retried(self):
        exc = RuntimeError("context_length_exceeded: prompt exceeds context window")
        self.assertEqual(self.classifier.failure_subtype(exception=exc), "context_length_exceeded")
        engine, worker = self.engine([exc])
        result = self.run_attempt(engine)
        self.assertEqual(result.policy.decision, ContinuationDecision.DEGRADE)
        self.assertEqual(result.failure_subtype, "context_length_exceeded")
        self.assertEqual(len(worker.calls), 1)

    def test_single_model_failure_has_no_retry(self):
        engine, worker = self.engine([RuntimeError("Model is unavailable."), {"content": "unused"}], router=False)
        result = self.run_attempt(engine)
        self.assertEqual(result.outcome, OutcomeType.PROVIDER_FAILURE)
        self.assertEqual(result.policy.decision, ContinuationDecision.DEGRADE)
        self.assertEqual(len(worker.calls), 1)
        self.assertEqual(self.store.get("S004").provider_retry_count, 0)

    def test_attempt_log_contains_section_scope_retry_and_policy_fields(self):
        engine, _ = self.engine([RuntimeError("upstream unavailable")])
        with self.assertLogs("hermes_agent.continuation_engine", level="INFO") as captured:
            self.run_attempt(engine)
        record = next(line for line in captured.output if "[CONTINUATION ATTEMPT]" in line)
        payload = json.loads(record.split("[CONTINUATION ATTEMPT] ", 1)[1])
        self.assertEqual(payload["request_id"], "req-observe-1")
        self.assertEqual(payload["section_id"], "S004")
        self.assertEqual(payload["requirement_id"], "req_http_500_definition")
        self.assertEqual(payload["requested_model_alias"], "9routerpc")
        self.assertTrue(payload["multi_model_router"])
        self.assertEqual(payload["provider_retry_count_before"], 0)
        self.assertEqual(payload["provider_retry_count_after"], 1)
        self.assertEqual(payload["policy_decision"], "CONTINUE")
        self.assertIn("section_store_state", payload)
        self.assertIn("final_section_status", payload)


if __name__ == "__main__":
    unittest.main()

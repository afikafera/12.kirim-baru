import json
import unittest

from hermes_agent.fact_checker import FactChecker, FactExtractionFailure


class ScriptedLLM:
    def __init__(self, outcomes, multi_model_router=True):
        self.outcomes = list(outcomes)
        self.multi_model_router = multi_model_router
        self.calls = []

    def is_multi_model_router(self):
        return self.multi_model_router

    def analyze(self, system_prompt, user_query, temperature=0.1, max_tokens=None):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_query": user_query,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FactExtractorStructuralOutputTests(unittest.TestCase):
    URL = "https://source.test/spec"
    EVIDENCE = [{
        "url": URL,
        "doc_type": "official_docs",
        "content": "The widget supports a 15 mm reference spacer.",
        "provenance": {"publisher": "source.test"},
    }]
    CHECKLIST = [{"field_id": "spacer", "label": "Reference spacer thickness"}]
    VALID = {
        "content": json.dumps({
            "source_url": URL,
            "source_type": "official_docs",
            "spacer": "15 mm",
        }),
        "finish_reason": "stop",
        "tokens_input": 1,
        "tokens_output": 1,
    }

    def _assert_same_work_retried(self, invalid_output):
        llm = ScriptedLLM([
            {"content": invalid_output, "finish_reason": "stop"},
            dict(self.VALID),
        ])
        evidence_before = json.loads(json.dumps(self.EVIDENCE))
        facts, _ = FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        self.assertGreater(len(facts), 0)
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[0]["system_prompt"], llm.calls[1]["system_prompt"])
        self.assertEqual(llm.calls[0]["user_query"], llm.calls[1]["user_query"])
        self.assertEqual(self.EVIDENCE, evidence_before)
        self.assertIn(self.URL, llm.calls[0]["user_query"])
        self.assertIn("15 mm reference spacer", llm.calls[0]["user_query"])
        self.assertEqual([c["max_tokens"] for c in llm.calls], [2048, 4096])

    def test_markdown_then_valid_json_retries_same_work(self):
        self._assert_same_work_retried("Here is the answer in prose, with no JSON.")

    def test_malformed_json_then_valid_json_retries_same_work(self):
        self._assert_same_work_retried('{"source_url": "broken", "facts": [')

    def test_wrong_schema_then_valid_json_retries_same_work(self):
        self._assert_same_work_retried('["facts are unavailable"]')

    def test_structural_invalid_exhaustion_is_explicit(self):
        llm = ScriptedLLM([
            {"content": "Markdown answer without JSON", "finish_reason": "stop"},
            {"content": "still not JSON", "finish_reason": "stop"},
        ])
        evidence_before = json.loads(json.dumps(self.EVIDENCE))
        with self.assertRaises(FactExtractionFailure) as raised:
            FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        self.assertEqual(getattr(raised.exception, "failure_class", None), "WORKER_OUTPUT_INVALID")
        self.assertEqual(getattr(raised.exception, "attempts", None), 2)
        self.assertEqual(self.EVIDENCE, evidence_before)
        self.assertEqual(len(llm.calls), 2)

    def test_valid_empty_object_is_not_retried_or_reclassified(self):
        llm = ScriptedLLM([
            {"content": "{}", "finish_reason": "stop"},
            dict(self.VALID),
        ])
        facts, _ = FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        self.assertEqual(facts, {})
        self.assertEqual(len(llm.calls), 1)

    def test_single_source_flat_json_compatibility_is_preserved(self):
        llm = ScriptedLLM([{"content": json.dumps({"spacer": "15 mm"}), "finish_reason": "stop"}])
        facts, _ = FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        self.assertGreater(len(facts), 0)
        self.assertEqual(len(llm.calls), 1)

    def test_fenced_valid_json_still_extracts(self):
        payload = {"source_url": self.URL, "source_type": "official_docs", "spacer": "15 mm"}
        llm = ScriptedLLM([{"content": f"```json\n{json.dumps(payload)}\n```", "finish_reason": "stop"}])
        facts, _ = FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        self.assertGreater(len(facts), 0)
        self.assertEqual(len(llm.calls), 1)

    def test_embedded_salvageable_json_still_extracts(self):
        payload = {"source_url": self.URL, "source_type": "official_docs", "spacer": "15 mm"}
        llm = ScriptedLLM([{"content": f"Result follows: {json.dumps(payload)}\nDone.", "finish_reason": "stop"}])
        facts, _ = FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        self.assertGreater(len(facts), 0)
        self.assertEqual(len(llm.calls), 1)

    def test_length_truncation_keeps_existing_salvage_path(self):
        partial = '{"source_url": "' + self.URL + '", "source_type": "official_docs", "spacer": "15 mm"'
        llm = ScriptedLLM([
            {"content": partial, "finish_reason": "length"},
            {"content": partial, "finish_reason": "length"},
        ])
        try:
            FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        except Exception as exc:
            self.assertNotEqual(getattr(exc, "failure_class", None), "WORKER_OUTPUT_INVALID")
            self.assertNotEqual(getattr(exc, "failure_class", None), "PROVIDER_EXHAUSTED")
        self.assertEqual(len(llm.calls), 2)

    def test_single_model_keeps_one_call_for_nonempty_invalid_output(self):
        llm = ScriptedLLM([
            {"content": "Markdown answer without JSON", "finish_reason": "stop"},
            dict(self.VALID),
        ], multi_model_router=False)
        facts, _ = FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        self.assertEqual(facts, {})
        self.assertEqual(len(llm.calls), 1)


class WorkerOutputInvalidRecoveryGuardTests(unittest.TestCase):
    def test_worker_output_invalid_is_not_recovery_eligibility(self):
        from unittest.mock import Mock
        from hermes_agent.orchestrator import HermesAgent

        agent = object.__new__(HermesAgent)
        agent._resolve_recovery_requirement = Mock(
            side_effect=AssertionError("recovery requirement was created")
        )
        recovery = agent._resolve_controller_recovery_requirement(
            "WORKER_OUTPUT_INVALID",
            {},
            {"goal": "fixed goal"},
            missing_items=["fixed requirement"],
            goal="fixed goal",
        )
        self.assertIsNone(recovery)
        agent._resolve_recovery_requirement.assert_not_called()


class WorkerOutputInvalidRecoveryGuardTests(unittest.TestCase):
    def test_worker_output_invalid_is_not_recovery_eligibility(self):
        from unittest.mock import Mock
        from hermes_agent.orchestrator import HermesAgent

        agent = object.__new__(HermesAgent)
        agent._resolve_recovery_requirement = Mock(
            side_effect=AssertionError("recovery requirement was created")
        )
        recovery = agent._resolve_controller_recovery_requirement(
            "WORKER_OUTPUT_INVALID",
            {},
            {"goal": "fixed goal"},
            missing_items=["fixed requirement"],
            goal="fixed goal",
        )
        self.assertIsNone(recovery)
        agent._resolve_recovery_requirement.assert_not_called()


if __name__ == "__main__":
    unittest.main()

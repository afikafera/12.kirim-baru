import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from hermes_agent.fact_checker import (
    FactChecker,
    FactExtractionFailure,
    WorkerOutputInvalid,
)


URL_A = "https://source.test/spec-a"
URL_B = "https://source.test/spec-b"
REQUIREMENT_ID = "R1"


def _json(url, source_type="official_docs", **facts):
    return json.dumps(
        {"source_url": url, "source_type": source_type, **facts},
        separators=(",", ":"),
    )


def _truncated(url, source_type="official_docs", **facts):
    # Leave one complete fact, then begin a later key and truncate its value.
    return _json(url, source_type, **facts)[:-1] + ',"unfinished_field":'


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
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _response(content, finish_reason="length", model="deepseek-flash"):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content),
            finish_reason=finish_reason,
        )],
        usage=None,
        model=model,
    )


class FactExtractorTruncationPreservationTests(unittest.TestCase):
    CONTENT = "Rated power is 500 W. Impedance is 8 ohm."
    CHECKLIST = [{
        "field_id": REQUIREMENT_ID,
        "label": "R1: rated power and impedance",
    }]

    def setUp(self):
        self.evidence = [{
            "evidence_id": "E1",
            "url": URL_A,
            "doc_type": "official_docs",
            "content": self.CONTENT,
            "provenance": {"publisher": "source.test", "record": "E1"},
        }]
        self.before = self._fingerprint(self.evidence)

    @staticmethod
    def _fingerprint(evidence):
        return tuple(
            (
                item.get("evidence_id"),
                item.get("url"),
                item.get("content"),
                json.dumps(item.get("provenance"), sort_keys=True),
            )
            for item in evidence
        )

    def _assert_fact(self, fact, value, source):
        self.assertEqual(fact.get("value"), value)
        self.assertEqual(fact.get("source"), source)
        self.assertEqual(fact.get("source_type"), "official_docs")
        self.assertTrue(any(
            observation.get("value") == value
            and observation.get("source") == source
            for observation in fact.get("sources", [])
        ))

    def _assert_same_work(self, llm, evidence=None):
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[0]["user_query"], llm.calls[1]["user_query"])
        self.assertEqual(llm.calls[0]["system_prompt"], llm.calls[1]["system_prompt"])
        self.assertEqual([call["max_tokens"] for call in llm.calls], [2048, 4096])
        self.assertIn(REQUIREMENT_ID, llm.calls[0]["user_query"])
        self.assertIn(URL_A, llm.calls[0]["user_query"])
        self.assertIn(self.CONTENT, llm.calls[0]["user_query"])
        if evidence is not None:
            self.assertEqual(self._fingerprint(evidence), self.before)

    def test_attempt_one_truncated_fact_is_merged_with_attempt_two_success(self):
        llm = ScriptedLLM([
            {"content": _truncated(URL_A, rated_power="500 W"), "finish_reason": "length"},
            {"content": _json(URL_A, impedance="8 ohm"), "finish_reason": "stop"},
        ])
        facts, _ = FactChecker(llm).extract_facts_batch(self.evidence, self.CHECKLIST)

        self._assert_same_work(llm, self.evidence)
        self.assertIn("rated_power", facts)
        self.assertIn("impedance", facts)
        self._assert_fact(facts["rated_power"], "500 W", URL_A)
        self._assert_fact(facts["impedance"], "8 ohm", URL_A)

    def test_truncated_root_missing_only_closing_brace_preserves_last_complete_fact(self):
        llm = ScriptedLLM([
            {"content": _json(URL_A, rated_power="500 W")[:-1], "finish_reason": "length"},
            {"content": _json(URL_A, impedance="8 ohm"), "finish_reason": "stop"},
        ])
        facts, _ = FactChecker(llm).extract_facts_batch(self.evidence, self.CHECKLIST)

        self.assertIn("rated_power", facts)
        self.assertIn("impedance", facts)
        self._assert_fact(facts["rated_power"], "500 W", URL_A)
        self._assert_fact(facts["impedance"], "8 ohm", URL_A)

    def test_two_truncated_attempts_preserve_facts_from_both(self):
        llm = ScriptedLLM([
            {"content": _truncated(URL_A, rated_power="500 W"), "finish_reason": "length"},
            {"content": _truncated(URL_A, impedance="8 ohm"), "finish_reason": "length"},
        ])
        facts, _ = FactChecker(llm).extract_facts_batch(self.evidence, self.CHECKLIST)

        self._assert_same_work(llm, self.evidence)
        self.assertEqual(set(facts), {"rated_power", "impedance"})
        self._assert_fact(facts["rated_power"], "500 W", URL_A)
        self._assert_fact(facts["impedance"], "8 ohm", URL_A)

    def test_identical_fact_from_both_attempts_is_deduplicated(self):
        llm = ScriptedLLM([
            {"content": _truncated(URL_A, rated_power="500 W"), "finish_reason": "length"},
            {"content": _truncated(URL_A, rated_power="500 W"), "finish_reason": "length"},
        ])
        facts, _ = FactChecker(llm).extract_facts_batch(self.evidence, self.CHECKLIST)

        self._assert_same_work(llm, self.evidence)
        self.assertEqual(set(facts), {"rated_power"})
        self._assert_fact(facts["rated_power"], "500 W", URL_A)
        self.assertEqual(len(facts["rated_power"].get("sources", [])), 1)

    def test_conflicting_values_retain_both_source_observations(self):
        evidence = [
            {
                "evidence_id": "E1", "url": URL_A, "doc_type": "official_docs",
                "content": "Rated power is 500 W.", "provenance": {"publisher": "A"},
            },
            {
                "evidence_id": "E2", "url": URL_B, "doc_type": "official_docs",
                "content": "Rated power is 450 W.", "provenance": {"publisher": "B"},
            },
        ]
        before = self._fingerprint(evidence)
        llm = ScriptedLLM([
            {"content": _truncated(URL_A, rated_power="500 W"), "finish_reason": "length"},
            {"content": _truncated(URL_B, rated_power="450 W"), "finish_reason": "length"},
        ])
        facts, _ = FactChecker(llm).extract_facts_batch(evidence, self.CHECKLIST)

        self.assertEqual(self._fingerprint(evidence), before)
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("rated_power", facts)
        observations = facts["rated_power"].get("sources", [])
        self.assertEqual(
            {(item.get("value"), item.get("source")) for item in observations},
            {("500 W", URL_A), ("450 W", URL_B)},
        )

    def test_two_unusable_truncations_raise_distinct_failure(self):
        llm = ScriptedLLM([
            {"content": '{"rated_power":', "finish_reason": "length"},
            {"content": '{"impedance":', "finish_reason": "length"},
        ])
        with self.assertRaises(FactExtractionFailure) as raised:
            FactChecker(llm).extract_facts_batch(self.evidence, self.CHECKLIST)

        self.assertEqual(raised.exception.failure_class, "TRUNCATED_OUTPUT_UNUSABLE")
        self.assertEqual(raised.exception.attempts, 2)
        self._assert_same_work(llm, self.evidence)

    def test_valid_empty_json_remains_an_ordinary_one_call_empty_result(self):
        llm = ScriptedLLM([{"content": "{}", "finish_reason": "stop"}])
        facts, _ = FactChecker(llm).extract_facts_batch(self.evidence, self.CHECKLIST)
        self.assertEqual(facts, {})
        self.assertEqual(len(llm.calls), 1)

    def test_nontruncated_invalid_output_remains_worker_output_invalid(self):
        llm = ScriptedLLM([
            {"content": "Markdown without JSON", "finish_reason": "stop"},
            {"content": "Still Markdown", "finish_reason": "stop"},
        ])
        with self.assertRaises(WorkerOutputInvalid) as raised:
            FactChecker(llm).extract_facts_batch(self.evidence, self.CHECKLIST)
        self.assertEqual(raised.exception.failure_class, "WORKER_OUTPUT_INVALID")
        self.assertEqual(len(llm.calls), 2)

    def test_truncated_output_unusable_is_not_recovery_eligible(self):
        from unittest.mock import Mock
        from hermes_agent.orchestrator import HermesAgent

        agent = object.__new__(HermesAgent)
        agent._resolve_recovery_requirement = Mock(
            side_effect=AssertionError("truncated provider output expanded scope")
        )
        recovery = agent._resolve_controller_recovery_requirement(
            "TRUNCATED_OUTPUT_UNUSABLE",
            {},
            {"goal": "fixed goal"},
            missing_items=["R1: rated power and impedance"],
            goal="fixed goal",
        )
        self.assertIsNone(recovery)
        agent._resolve_recovery_requirement.assert_not_called()

    def test_deepseek_keeps_single_model_retry_and_preserves_truncated_fact(self):
        config = {
            "LLM_DEFAULT_MODEL": "deepseek-chat",
            "LLM_PROVIDER_DEEPSEEK_API_KEY": "test-key",
            "LLM_PROVIDER_DEEPSEEK_BASE_URL": "https://deepseek.test/v1",
            "LLM_PROVIDER_DEEPSEEK_MODEL": "deepseek-flash",
            "LLM_PROVIDER_DEEPSEEK_ALIASES": "deepseek-chat",
            "LLM_PROVIDER_DEEPSEEK_MULTI_MODEL_ROUTER": "false",
        }
        from llm_analyzer.analyzer import LLMAnalyzer

        with patch("llm_analyzer.analyzer.OpenAI") as openai:
            client = openai.return_value
            client.chat.completions.create.side_effect = [
                _response(_truncated(URL_A, rated_power="500 W"), "length"),
                _response(_json(URL_A, impedance="8 ohm"), "stop"),
            ]
            analyzer = LLMAnalyzer(config)
            with analyzer.use_model("deepseek-chat"):
                self.assertEqual(analyzer.get_requested_model(), "deepseek-chat")
                self.assertFalse(analyzer.is_multi_model_router())
                with redirect_stdout(io.StringIO()):
                    facts, _ = FactChecker(analyzer).extract_facts_batch(self.evidence, self.CHECKLIST)

            calls = client.chat.completions.create.call_args_list
            self.assertEqual(len(calls), 2)
            self.assertEqual([call.kwargs["model"] for call in calls], ["deepseek-flash", "deepseek-flash"])
            self.assertEqual([call.kwargs["max_tokens"] for call in calls], [2048, 4096])
            self.assertEqual(analyzer.get_requested_model(), "deepseek-chat")
            self.assertEqual(set(facts), {"rated_power", "impedance"})
            self._assert_fact(facts["rated_power"], "500 W", URL_A)
            self._assert_fact(facts["impedance"], "8 ohm", URL_A)


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from unittest.mock import patch

from hermes_agent.fact_checker import FactChecker


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


class ProviderExhaustedBaselineTests(unittest.TestCase):
    URL = "https://source.test/spec"
    EVIDENCE = [{
        "url": URL, "doc_type": "official_docs",
        "content": "The widget supports a 15 mm reference spacer.",
        "provenance": {"publisher": "source.test"},
    }]
    CHECKLIST = [{"field_id": "spacer", "label": "Reference spacer thickness"}]

    def test_provider_failure_then_success_reuses_identical_work(self):
        payload = {"source_url": self.URL, "source_type": "official_docs", "spacer": "15 mm"}
        llm = ScriptedLLM([
            RuntimeError("HTTP 400 Model is unavailable"),
            {"content": json.dumps(payload), "tokens_input": 1, "tokens_output": 1},
        ])
        facts, _ = FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)

        self.assertGreater(len(facts), 0)
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[0]["user_query"], llm.calls[1]["user_query"])
        self.assertIn(self.URL, llm.calls[0]["user_query"])
        self.assertIn("15 mm reference spacer", llm.calls[0]["user_query"])
        self.assertEqual(llm.calls[0]["max_tokens"], 2048)
        self.assertEqual(llm.calls[1]["max_tokens"], 4096)

    def test_provider_exhaustion_is_not_an_ordinary_empty_extraction(self):
        from hermes_agent.fact_checker import ProviderExhausted

        llm = ScriptedLLM([
            RuntimeError("HTTP 400 Model is unavailable"),
            RuntimeError("HTTP 400 Model is unavailable"),
        ])
        evidence_before = json.loads(json.dumps(self.EVIDENCE))
        with self.assertRaises(ProviderExhausted) as raised:
            FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)

        self.assertEqual(self.EVIDENCE, evidence_before)
        self.assertEqual(raised.exception.failure_class, "PROVIDER_EXHAUSTED")
        self.assertEqual(raised.exception.attempts, 2)
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[0]["user_query"], llm.calls[1]["user_query"])

    def test_orchestrator_does_not_turn_provider_exhaustion_into_recovery(self):
        from unittest.mock import Mock
        from hermes_agent.orchestrator import HermesAgent

        agent = object.__new__(HermesAgent)
        agent._resolve_recovery_requirement = Mock(side_effect=AssertionError("scope expanded"))
        recovery = agent._resolve_controller_recovery_requirement(
            "PROVIDER_EXHAUSTED", {}, {"goal": "fixed goal"},
            missing_items=["fixed requirement"], goal="fixed goal",
        )
        self.assertIsNone(recovery)
        agent._resolve_recovery_requirement.assert_not_called()

    def test_valid_empty_extraction_is_not_a_provider_call_failure(self):
        llm = ScriptedLLM([{"content": "{}", "tokens_input": 1, "tokens_output": 1}])
        facts, _ = FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        self.assertEqual(facts, {})
        self.assertEqual(len(llm.calls), 1)

    def test_null_content_exhaustion_is_provider_failure(self):
        from hermes_agent.fact_checker import ProviderExhausted
        llm = ScriptedLLM([{"content": None}, {"content": "  "}])
        with self.assertRaises(ProviderExhausted):
            FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        self.assertEqual(len(llm.calls), 2)

    def test_gateway_5xx_retries_within_existing_budget(self):
        from hermes_agent.fact_checker import ProviderExhausted

        class GatewayFailure(RuntimeError):
            status_code = 503

        llm = ScriptedLLM([GatewayFailure("upstream failure"), GatewayFailure("upstream failure")])
        with self.assertRaises(ProviderExhausted):
            FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        self.assertEqual(len(llm.calls), 2)

    def test_unsupported_internal_model_400_is_retryable(self):
        from hermes_agent.fact_checker import ProviderExhausted

        class GatewayFailure(RuntimeError):
            status_code = 400

        llm = ScriptedLLM([GatewayFailure("Unsupported model"), GatewayFailure("Unsupported model")])
        with self.assertRaises(ProviderExhausted):
            FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        self.assertEqual(len(llm.calls), 2)

    def test_length_truncation_is_not_classified_as_provider_exhaustion(self):
        from hermes_agent.fact_checker import ProviderExhausted
        partial = '{"source_url":"' + self.URL + '", "spacer": "15 mm"'
        llm = ScriptedLLM([
            {"content": partial, "finish_reason": "length"},
            {"content": partial, "finish_reason": "length"},
        ])
        try:
            FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        except ProviderExhausted:
            self.fail("partial length-truncated content was misclassified as provider exhaustion")
        self.assertEqual(len(llm.calls), 2)

    def test_auth_failure_is_terminal_and_not_retried(self):
        from hermes_agent.fact_checker import FactExtractionFailure
        llm = ScriptedLLM([RuntimeError("HTTP 401 Unauthorized")])
        with self.assertRaises(FactExtractionFailure) as raised:
            FactChecker(llm).extract_facts_batch(self.EVIDENCE, self.CHECKLIST)
        self.assertEqual(raised.exception.failure_class, "TERMINAL_REQUEST_FAILURE")
        self.assertEqual(len(llm.calls), 1)


class DeepSeekBaselineTests(unittest.TestCase):
    def test_deepseek_fact_extraction_keeps_existing_two_call_retry(self):
        llm = ScriptedLLM([
            RuntimeError("HTTP 400 Model is unavailable"),
            RuntimeError("HTTP 400 Model is unavailable"),
        ], multi_model_router=False)
        facts, _ = FactChecker(llm).extract_facts_batch(
            ProviderExhaustedBaselineTests.EVIDENCE,
            ProviderExhaustedBaselineTests.CHECKLIST,
        )
        self.assertEqual(facts, {})
        self.assertEqual(len(llm.calls), 2)

    def test_deepseek_alias_model_and_single_call_are_unchanged(self):
        config = {
            "LLM_DEFAULT_MODEL": "deepseek-chat",
            "LLM_PROVIDER_DEEPSEEK_API_KEY": "test-key",
            "LLM_PROVIDER_DEEPSEEK_BASE_URL": "https://deepseek.test/v1",
            "LLM_PROVIDER_DEEPSEEK_MODEL": "deepseek-chat",
            "LLM_PROVIDER_DEEPSEEK_ALIASES": "deepseek-chat",
            "LLM_PROVIDER_DEEPSEEK_MULTI_MODEL_ROUTER": "false",
        }
        from llm_analyzer.analyzer import LLMAnalyzer

        with patch("llm_analyzer.analyzer.OpenAI") as openai:
            client = openai.return_value
            client.chat.completions.create.return_value = type("Response", (), {
                "choices": [type("Choice", (), {
                    "message": type("Message", (), {"content": "OK"})(),
                    "finish_reason": "stop",
                })()],
                "usage": None,
                "model": "deepseek-chat",
            })()
            analyzer = LLMAnalyzer(config)
            self.assertEqual(analyzer.get_requested_model(), "deepseek-chat")
            self.assertFalse(analyzer.is_multi_model_router("deepseek-chat"))
            result = analyzer.analyze("system", "tiny prompt")

        self.assertEqual(result["model"], "deepseek-chat")
        self.assertEqual(result["content"], "OK")
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(client.chat.completions.create.call_args.kwargs["model"], "deepseek-chat")


if __name__ == "__main__":
    unittest.main()

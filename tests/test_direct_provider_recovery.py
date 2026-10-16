"""Offline DIRECT recovery tests: provider calls are scripted, pipeline calls trapped."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import hermes_agent.direct_provider_recovery as recovery
from hermes_agent.direct_provider_recovery import DirectProviderFailure
from test_direct_answer_semantics import (
    AranAgent, SemanticRouter, Trap, TRAIN_QUERY, orchestrator,
)

CAPACITY_ERROR = RuntimeError(
    "LLM provider '9routerpc' returned empty or null choices: "
    "provider_unavailable ResourceExhausted Worker local total request limit reached (16/16)"
)


class ScriptedProvider:
    def __init__(self, script, router=True):
        self.script = iter(script)
        self.router = router
        self.calls = []

    def is_multi_model_router(self):
        return self.router

    def get_requested_model(self):
        return "9routerpc" if self.router else "deepseek-chat"

    def analyze(self, **kwargs):
        self.calls.append(dict(kwargs))
        result = next(self.script)
        if isinstance(result, Exception):
            raise result
        return result


class DirectProviderRecoveryTests(unittest.TestCase):
    def run_agent(self, llm):
        counters = {key: 0 for key in ("planner", "search", "fetch", "facts", "kg")}
        agent = AranAgent.__new__(AranAgent)
        agent.router = SemanticRouter()
        agent.skill_router = SimpleNamespace(select=lambda q: None)
        agent.user_memory = SimpleNamespace(search=lambda q: [])
        agent.llm = llm
        for field, key in (("task_planner", "planner"), ("searcher", "search"),
                           ("skill_bridge", "fetch"), ("facts", "facts")):
            setattr(agent, field, Trap(counters, key))

        def kg_trap():
            counters["kg"] += 1
            raise AssertionError("unexpected KG construction")

        self.counters = counters
        with patch.object(orchestrator, "TokenProfiler", lambda: object()), \
             patch.object(orchestrator, "LatencyProfiler", lambda: object()), \
             patch.object(orchestrator, "log_event", lambda *a, **k: None), \
             patch.object(orchestrator, "KnowledgeGraph", kg_trap), \
             patch.object(orchestrator, "enforce_direct_answer", side_effect=lambda _llm, result, **_kw: result["content"]):
            # Provider retry isolation; sentinel strings are not evidence of
            # grounding acceptance, which has its own integration suite.
            return agent.research(
                TRAIN_QUERY, context="Prior user context",
                attachments=[{"content": "User supplied attachment"}],
                request_id="direct-api-test",
            )

    def tearDown(self):
        if hasattr(self, "counters"):
            self.assertTrue(all(value == 0 for value in self.counters.values()))

    @patch.object(recovery.time, "sleep")
    def test_router_capacity_failure_then_success_preserves_entire_prompt(self, sleep):
        llm = ScriptedProvider([CAPACITY_ERROR, {"content": "recovered"}])
        self.assertEqual(self.run_agent(llm), "recovered")
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[0], llm.calls[1])
        self.assertIn("Prior user context", llm.calls[1]["user_query"])
        self.assertIn("User supplied attachment", llm.calls[1]["user_query"])
        self.assertNotIn("model", llm.calls[1])
        sleep.assert_called_once_with(1.0)

    @patch.object(recovery.time, "sleep")
    def test_router_exhaustion_has_two_attempts_and_safe_error(self, sleep):
        llm = ScriptedProvider([CAPACITY_ERROR, CAPACITY_ERROR])
        with self.assertRaises(DirectProviderFailure) as caught:
            self.run_agent(llm)
        failure = caught.exception
        self.assertEqual((failure.status_code, failure.attempts), (503, 2))
        self.assertEqual(failure.failure_class, "PROVIDER_EXHAUSTED")
        self.assertEqual(failure.request_id, "direct-api-test")
        self.assertNotIn("ResourceExhausted", str(failure.public_error()))
        self.assertEqual(len(llm.calls), 2)
        sleep.assert_called_once()

    @patch.object(recovery.time, "sleep")
    def test_deepseek_failure_is_not_retried_or_rotated(self, sleep):
        llm = ScriptedProvider([RuntimeError("service unavailable")], router=False)
        with self.assertRaises(DirectProviderFailure) as caught:
            self.run_agent(llm)
        self.assertEqual(caught.exception.attempts, 1)
        self.assertEqual(caught.exception.requested_model, "deepseek-chat")
        self.assertEqual(len(llm.calls), 1)
        sleep.assert_not_called()

    @patch.object(recovery.time, "sleep")
    def test_terminal_input_and_model_errors_are_not_retried(self, sleep):
        for message, status in [
            ("context_length_exceeded", 400),
            ("tokens per minute request too large", 400),
            ("unsupported model", 502),
        ]:
            with self.subTest(message=message):
                llm = ScriptedProvider([RuntimeError(message)])
                with self.assertRaises(DirectProviderFailure) as caught:
                    self.run_agent(llm)
                self.assertEqual(caught.exception.status_code, status)
                self.assertEqual(caught.exception.failure_class, "TERMINAL_REQUEST_FAILURE")
                self.assertEqual(len(llm.calls), 1)
        sleep.assert_not_called()

    @patch.object(recovery.time, "sleep")
    def test_timeout_and_transient_failure_recover(self, sleep):
        for error in [TimeoutError("timed out"), RuntimeError("provider unavailable")]:
            with self.subTest(error=type(error).__name__):
                llm = ScriptedProvider([error, {"content": "answer"}])
                self.assertEqual(self.run_agent(llm), "answer")
                self.assertEqual(len(llm.calls), 2)
        self.assertEqual(sleep.call_count, 2)

    @patch.object(recovery.time, "sleep")
    def test_empty_outputs_recover_but_invalid_type_is_terminal(self, sleep):
        for result in [None, {}, {"content": None}, {"content": "  "}]:
            llm = ScriptedProvider([result, {"content": "answer"}])
            self.assertEqual(self.run_agent(llm), "answer")
        llm = ScriptedProvider([{"content": {"wrong": "type"}}])
        with self.assertRaises(DirectProviderFailure) as caught:
            self.run_agent(llm)
        self.assertEqual(caught.exception.failure_class, "INVALID_PROVIDER_OUTPUT")
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(sleep.call_count, 4)

    @patch.object(recovery.time, "sleep")
    def test_success_is_one_call_and_keeps_truncated_content_behavior(self, sleep):
        for router in [True, False]:
            llm = ScriptedProvider([{"content": "partial content", "finish_reason": "length"}], router)
            self.assertEqual(self.run_agent(llm), "partial content")
            self.assertEqual(len(llm.calls), 1)
        sleep.assert_not_called()

    @patch.object(recovery.time, "sleep")
    def test_programming_and_unknown_errors_are_not_masked(self, sleep):
        for error in [ValueError("unknown configured alias"), TypeError("bug"), RuntimeError("unclassified bug")]:
            llm = ScriptedProvider([error])
            with self.assertRaises(type(error)) as caught:
                self.run_agent(llm)
            self.assertIs(caught.exception, error)
            self.assertEqual(len(llm.calls), 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()

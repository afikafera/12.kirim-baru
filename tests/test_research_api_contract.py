import os
import sys
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, ".")

_AUTH_ENV_KEYS = (
    "HERMES_LOGIN_USERNAME",
    "HERMES_LOGIN_USER_ID",
    "HERMES_LOGIN_PASSWORD_HASH",
    "HERMES_SESSION_COOKIE_SECURE",
    "HERMES_SESSION_TTL_SECONDS",
)
_ORIGINAL_AUTH_ENV = {key: os.environ.get(key) for key in _AUTH_ENV_KEYS}
os.environ.update({
    "HERMES_LOGIN_USERNAME": "contract-test",
    "HERMES_LOGIN_USER_ID": "contract-test-user",
    "HERMES_LOGIN_PASSWORD_HASH": "scrypt$32768$8$3$" + "00" * 16 + "$" + "00" * 32,
    "HERMES_SESSION_COOKIE_SECURE": "false",
    "HERMES_SESSION_TTL_SECONDS": "3600",
})


class FakeMemoryManager:
    def __init__(self, _config):
        pass

    def persist_chat_exchange(self, **kwargs):
        return {"id": str(kwargs["conversation_id"])}

    def get_conversation(self, *_args):
        return None


class FakeCalibrator:
    def __init__(self, *_args):
        pass


class FakeLLM:
    default_model = "deepseek-chat"
    providers = {}

    def __init__(self, *_args):
        pass

    def use_model(self, _model):
        return nullcontext()


class FakeOutcomeLogger:
    def __init__(self, *_args):
        pass


class FakeLessonsEngine:
    def __init__(self, *_args):
        pass


class FakeAranAgent:
    result = {
        "goal": "contract goal",
        "answer": "useful answer",
        "research_status": "DONE",
        "facts_count": 2,
        "provider_failures": {},
        "research": {
            "status": "DONE",
            "status_detail": "DONE",
            "degraded": False,
            "facts_count": 2,
            "provider_failures": {},
            "aggregator_status": "DONE",
        },
    }

    def __init__(self, _mm, _cal, _llm, _outcome, _lessons):
        self.llm = _llm

    def research(self, *_args, **_kwargs):
        return dict(self.result)


import calibration.calibrator as calibrator_module
import hermes_agent.orchestrator as orchestrator_module
import lessons_engine.engine as lessons_module
import llm_analyzer.analyzer as llm_module
import memory_manager.manager as manager_module
import outcome_logger.logger as outcome_module

with (
    patch.object(manager_module, "MemoryManager", FakeMemoryManager),
    patch.object(calibrator_module, "ConfidenceCalibrator", FakeCalibrator),
    patch.object(llm_module, "LLMAnalyzer", FakeLLM),
    patch.object(outcome_module, "OutcomeLogger", FakeOutcomeLogger),
    patch.object(lessons_module, "LessonsEngine", FakeLessonsEngine),
    patch.object(orchestrator_module, "AranAgent", FakeAranAgent),
):
    import api.main as api_main

for _key, _value in _ORIGINAL_AUTH_ENV.items():
    if _value is None:
        os.environ.pop(_key, None)
    else:
        os.environ[_key] = _value


class ResearchApiContractTests(unittest.IsolatedAsyncioTestCase):
    def test_research_endpoint_preserves_canonical_metadata_and_legacy_fields(self):
        result = api_main.research(api_main.ResearchRequest(query="query"))
        self.assertEqual(result["goal"], "contract goal")
        self.assertEqual(result["research_status"], "DONE")
        self.assertEqual(result["facts_count"], 2)
        self.assertIn("provider_failures", result)
        self.assertEqual(result["research"]["status"], "DONE")

    def test_research_endpoint_exposes_terminal_failure_detail(self):
        result_data = {
            "goal": "contract goal",
            "answer": "partial evidence retained",
            "research_status": "PROVIDER_EXHAUSTED",
            "facts_count": 0,
            "provider_failures": {"R1": {"failure_class": "PROVIDER_EXHAUSTED"}},
        }
        with patch.object(api_main.aran, "research", return_value=result_data):
            result = api_main.research(api_main.ResearchRequest(query="query"))
        self.assertEqual(result["research_status"], "PROVIDER_EXHAUSTED")
        self.assertEqual(result["research"]["status"], "FAILED")
        self.assertEqual(result["research"]["failure_class"], "PROVIDER_EXHAUSTED")
        self.assertEqual(result["provider_failures"], result_data["provider_failures"])

    def test_research_endpoint_recomputes_canonical_status_from_aggregator(self):
        result_data = {
            "goal": "contract goal",
            "answer": "useful answer",
            "research_status": "DONE",
            "facts_count": 2,
            "provider_failures": {},
            "research": {"aggregator_status": "PARTIAL"},
        }
        with patch.object(api_main.aran, "research", return_value=result_data):
            result = api_main.research(api_main.ResearchRequest(query="query"))
        self.assertEqual(result["research_status"], "DONE")
        self.assertEqual(result["research"]["status"], "PARTIAL")
        self.assertEqual(result["answer"], "useful answer")

    async def test_chat_completion_exposes_partial_and_failed_without_changing_choices(self):
        request = SimpleNamespace(state=SimpleNamespace(user_id="contract-test-user"))
        observations = [
            ("INCOMPLETE", "PARTIAL", "PARTIAL"),
            ("DONE", "FAILED", "FAILED"),
        ]
        with patch("langfuse.get_client", return_value=SimpleNamespace(
            start_as_current_observation=lambda **_kwargs: nullcontext()
        )):
            for detail, aggregate, expected in observations:
                result_data = {
                    "goal": "contract goal",
                    "answer": "useful answer",
                    "research_status": detail,
                    "facts_count": 2,
                    "provider_failures": {},
                    "research": {"aggregator_status": aggregate},
                }
                with patch.object(api_main.aran, "research", return_value=result_data):
                    result = await api_main.chat_completions(
                        {"messages": [{"role": "user", "content": "query"}]}, request
                    )
                self.assertEqual(result["research"]["status"], expected)
                self.assertEqual(result["choices"][0]["message"]["content"], "useful answer")
                self.assertEqual(result["choices"][0]["finish_reason"], "stop")

    async def test_chat_completion_keeps_openai_shape_and_adds_research_metadata(self):
        request = SimpleNamespace(state=SimpleNamespace(user_id="contract-test-user"))
        with patch("langfuse.get_client", return_value=SimpleNamespace(
            start_as_current_observation=lambda **_kwargs: nullcontext()
        )):
            result = await api_main.chat_completions(
                {"model": "deepseek-chat", "messages": [{"role": "user", "content": "query"}]}, request
            )
        self.assertEqual(result["id"], "contract goal")
        self.assertEqual(result["object"], "chat.completion")
        self.assertEqual(result["model"], "deepseek-chat")
        self.assertEqual(result["choices"][0]["message"], {
            "role": "assistant", "content": "useful answer"
        })
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")
        self.assertEqual(result["research"]["status"], "DONE")
        self.assertIn("conversation_id", result)


if __name__ == "__main__":
    unittest.main()

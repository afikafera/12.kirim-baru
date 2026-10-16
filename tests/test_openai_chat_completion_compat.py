import unittest
import time
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Request
from openai.types.chat import ChatCompletion

# Reuse the isolated API fixture: fake Hermes, fake persistence, no database.
import test_research_api_contract as api_fixture

api = api_fixture.api_main
CONVERSATION_ID = "00000000-0000-4000-8000-000000000123"


def research_result(status):
    detail = (
        "DONE" if status in {"DONE", "PARTIAL"}
        else "PROVIDER_EXHAUSTED" if status == "FAILED"
        else status
    )
    aggregator = {"DONE": "DONE", "PARTIAL": "PARTIAL"}.get(status)
    failed = status == "FAILED"
    failure_class = detail if failed else None
    failures = (
        {"R1": {"failure_class": failure_class, "attempts": 2}}
        if failed else {}
    )
    return {
        "goal": "compatibility goal",
        "answer": "Assistant content remains unchanged.",
        "research_status": detail,
        "facts_count": 1 if status != "FAILED" else 0,
        "provider_failures": failures,
        "research": {
            "status": status,
            "status_detail": detail,
            "failure_class": failure_class,
            "degraded": status != "DONE",
            "facts_count": 1 if status != "FAILED" else 0,
            "provider_failures": failures,
            "aggregator_status": aggregator,
        },
    }


class OpenAIChatCompletionCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def build_response(self, status):
        request = SimpleNamespace(state=SimpleNamespace(user_id="contract-test-user"))
        with (
            patch.object(api.aran, "research", return_value=research_result(status)),
            patch.object(api.mm, "persist_chat_exchange", return_value={"id": CONVERSATION_ID}),
            patch("langfuse.get_client", return_value=SimpleNamespace(
                start_as_current_observation=lambda **_kwargs: nullcontext()
            )),
        ):
            return await api.chat_completions(
                {
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": "compatibility goal"}],
                },
                request,
            )

    def assert_sdk_response(self, response, status):
        parsed = ChatCompletion.model_validate(response)
        self.assertIs(type(response["created"]), int)
        self.assertLessEqual(int(time.time()) - response["created"], 2)
        self.assertGreaterEqual(response["created"], int(time.time()) - 2)
        self.assertEqual(parsed.model, "deepseek-chat")
        self.assertEqual(parsed.choices[0].message.content, "Assistant content remains unchanged.")
        self.assertEqual(parsed.choices[0].finish_reason, "stop")
        self.assertEqual(parsed.model_extra["research"]["status"], status)
        self.assertEqual(parsed.model_extra["conversation_id"], CONVERSATION_ID)
        self.assertNotIn("usage", response)
        return parsed

    async def test_done_parses_and_preserves_response(self):
        response = await self.build_response("DONE")
        parsed = self.assert_sdk_response(response, "DONE")
        self.assertEqual(parsed.model_extra["research"]["status_detail"], "DONE")

    async def test_partial_parses_and_preserves_research_extension(self):
        response = await self.build_response("PARTIAL")
        parsed = self.assert_sdk_response(response, "PARTIAL")
        self.assertEqual(parsed.model_extra["research"]["status_detail"], "DONE")

    async def test_failed_parses_and_preserves_exact_failure_class(self):
        response = await self.build_response("FAILED")
        parsed = self.assert_sdk_response(response, "FAILED")
        self.assertEqual(parsed.model_extra["research"]["failure_class"], "PROVIDER_EXHAUSTED")
        self.assertEqual(parsed.model_extra["research"]["status_detail"], "PROVIDER_EXHAUSTED")

    async def test_deepseek_model_and_message_shape_are_unchanged(self):
        response = await self.build_response("DONE")
        self.assertEqual(response["model"], "deepseek-chat")
        self.assertEqual(response["choices"][0]["message"], {
            "role": "assistant", "content": "Assistant content remains unchanged."
        })
        self.assertIsInstance(response["created"], int)

    async def test_arans_extensions_survive_sdk_parsing(self):
        response = await self.build_response("DONE")
        parsed = ChatCompletion.model_validate(response)
        self.assertEqual(parsed.model_extra["conversation_id"], CONVERSATION_ID)
        self.assertEqual(parsed.model_extra["research"]["status"], "DONE")


    async def test_http_status_remains_200_for_done_partial_and_failed(self):
        app = FastAPI()

        @app.post("/chat/completions")
        async def route(body: dict, request: Request):
            request.state.user_id = "contract-test-user"
            return await api.chat_completions(body, request)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for status in ("DONE", "PARTIAL", "FAILED"):
                with (
                    patch.object(api.aran, "research", return_value=research_result(status)),
                    patch.object(api.mm, "persist_chat_exchange", return_value={"id": CONVERSATION_ID}),
                    patch("langfuse.get_client", return_value=SimpleNamespace(
                        start_as_current_observation=lambda **_kwargs: nullcontext()
                    )),
                ):
                    response = await client.post("/chat/completions", json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": "compatibility goal"}],
                    })
                self.assertEqual(response.status_code, 200, status)
                parsed = ChatCompletion.model_validate(response.json())
                self.assertEqual(parsed.model_extra["research"]["status"], status)


if __name__ == "__main__":
    unittest.main()

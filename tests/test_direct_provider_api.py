"""ASGI contract tests; no provider calls, database or live service."""
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Request
from hermes_agent.direct_provider_recovery import DirectProviderFailure
import test_research_api_contract as fixture

api = fixture.api_main


class DirectProviderApiTests(unittest.IsolatedAsyncioTestCase):
    async def send(self, failure, endpoint="/chat/completions"):
        app = FastAPI()
        app.add_exception_handler(DirectProviderFailure, api.direct_provider_failure_handler)

        @app.post("/chat/completions")
        async def chat(body: dict, request: Request):
            request.state.user_id = "contract-test-user"
            return await api.chat_completions(body, request)

        @app.post("/research")
        def research(body: dict):
            return api.research(api.ResearchRequest(query=body["query"], model="9routerpc"))

        with patch.object(api.aran, "research", side_effect=failure), \
             patch.object(api.mm, "persist_chat_exchange") as persist, \
             patch("langfuse.get_client", return_value=SimpleNamespace(
                 start_as_current_observation=lambda **kwargs: nullcontext())):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                result = await client.post(endpoint, json={
                    "model": "9routerpc", "query": "5+5",
                    "messages": [{"role": "user", "content": "5+5"}],
                })
            persist.assert_not_called()
        return result

    async def test_exhaustion_is_structured_503_without_fake_success_or_research(self):
        failure = DirectProviderFailure("null_output", 2, "9routerpc", "req-test")
        result = await self.send(failure)
        self.assertEqual(result.status_code, 503)
        payload = result.json()
        self.assertEqual(payload["error"]["code"], "PROVIDER_EXHAUSTED")
        self.assertEqual(payload["error"]["route"], "DIRECT")
        self.assertEqual(payload["error"]["attempts"], 2)
        self.assertEqual(payload["error"]["request_id"], "req-test")
        self.assertNotIn("choices", payload)
        self.assertNotIn("research", payload)
        self.assertNotIn("Traceback", result.text)

    async def test_terminal_input_is_400(self):
        result = await self.send(DirectProviderFailure("context_length_exceeded", 1, "9routerpc"))
        self.assertEqual(result.status_code, 400)
        self.assertFalse(result.json()["error"]["retryable"])

    async def test_invalid_provider_output_is_502(self):
        result = await self.send(DirectProviderFailure("invalid_output", 1, "9routerpc"))
        self.assertEqual(result.status_code, 502)
        self.assertEqual(result.json()["error"]["code"], "INVALID_PROVIDER_OUTPUT")

    async def test_research_endpoint_direct_failure_uses_same_handler(self):
        result = await self.send(DirectProviderFailure("transient_unavailable", 2), "/research")
        self.assertEqual(result.status_code, 503)

    def test_handler_is_registered_on_real_app(self):
        self.assertIs(api.app.exception_handlers[DirectProviderFailure], api.direct_provider_failure_handler)


if __name__ == "__main__":
    unittest.main()

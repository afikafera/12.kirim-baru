"""Offline request-end log labels; no provider, database, or live service."""
import io
import unittest
from contextlib import nullcontext, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Request

import test_direct_answer_grounding as grounding
import test_research_api_contract as fixture
from hermes_agent.direct_answer_grounding import DirectOutputFailure
from hermes_agent.direct_provider_recovery import DirectProviderFailure

api = fixture.api_main


class RequestEndLabelTests(unittest.IsolatedAsyncioTestCase):
    async def _success(self, route, result):
        output = io.StringIO()

        def fake_research(*_args, **_kwargs):
            if callable(result):
                return result()
            marker = getattr(api, "REQUEST_END_ROUTE", None)
            if marker is not None:
                marker.set(route)
            return result

        request = SimpleNamespace(state=SimpleNamespace(user_id="contract-test-user"))
        with patch.object(api.aran, "research", side_effect=fake_research), patch(
            "langfuse.get_client", return_value=SimpleNamespace(
                start_as_current_observation=lambda **_kwargs: nullcontext()
            )
        ), redirect_stdout(output):
            response = await api.chat_completions(
                {"model": "deepseek-chat", "messages": [{"role": "user", "content": "example"}]},
                request,
            )
        return output.getvalue(), response

    async def test_direct_success_ends_direct(self):
        helper = grounding.DirectGroundingTests("test_generic_missing_parameter_remains_unknown")
        query = "3 boxes, total weight? weight per box not given"
        output, response = await self._success(
            "direct", lambda: helper.run_direct(
                query, [grounding.proof(unknowns=["weight per box"])]
            )[0]
        )
        self.assertIn("UNKNOWN", response["choices"][0]["message"]["content"])
        self.assertRegex(output, r"\[REQ [0-9a-f]{8}\] END direct\n")
        self.assertNotIn("END research", output)

    async def test_research_success_ends_research(self):
        output, response = await self._success("research", {
            "goal": "query", "answer": "sourced answer", "research_status": "DONE",
            "research": {"aggregator_status": "DONE"},
        })
        self.assertEqual(response["choices"][0]["message"]["content"], "sourced answer")
        self.assertRegex(output, r"\[REQ [0-9a-f]{8}\] END research\n")
        self.assertNotIn("END direct", output)

    async def test_memory_success_keeps_existing_label(self):
        output, _response = await self._success("memory", "Dicatat: example")
        self.assertRegex(output, r"\[REQ [0-9a-f]{8}\] END research\n")

    async def test_direct_failures_keep_existing_label(self):
        app = FastAPI()
        app.add_exception_handler(DirectProviderFailure, api.direct_provider_failure_handler)

        @app.post("/chat/completions")
        async def chat(body: dict, request: Request):
            request.state.user_id = "contract-test-user"
            return await api.chat_completions(body, request)

        failures = (
            DirectProviderFailure("null_output", 2, "deepseek-chat", "provider-id"),
            DirectOutputFailure("unsupported_fact", 2, "deepseek-chat", "grounding-id"),
        )
        for failure in failures:
            with self.subTest(failure=failure.failure_class):
                output = io.StringIO()
                with patch.object(api.aran, "research", side_effect=failure), patch(
                    "langfuse.get_client", return_value=SimpleNamespace(
                        start_as_current_observation=lambda **_kwargs: nullcontext()
                    )
                ), redirect_stdout(output):
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app), base_url="http://test"
                    ) as client:
                        response = await client.post("/chat/completions", json={
                            "model": "deepseek-chat",
                            "messages": [{"role": "user", "content": "example"}],
                        })
                self.assertEqual(response.status_code, failure.status_code)
                self.assertIn(
                    f"[REQ {failure.request_id}] END direct provider_failure "
                    f"code={failure.failure_class} attempts={failure.attempts}",
                    output.getvalue(),
                )
                self.assertNotIn("END research", output.getvalue())


if __name__ == "__main__":
    unittest.main()

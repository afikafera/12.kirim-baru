"""Offline HTTP/persistence acceptance for the real DIRECT coding branch."""
import socket
import unittest
from unittest.mock import patch
from hermes_agent.semantic_router import SemanticRouter
import test_direct_answer_grounding as grounding
import test_direct_grounding_api as api_fixture
from test_direct_coding import CODE, FENCED, QUERY


class CodingApiTests(unittest.IsolatedAsyncioTestCase):
    async def send(self, outputs):
        helper = api_fixture.DirectGroundingApiTests(
            "test_generic_missing_parameter_has_200_unknown")
        with patch.object(grounding, "DirectRouter", SemanticRouter), \
             patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            return await helper.send(QUERY, outputs)

    async def test_valid_code_reaches_api_and_persistence(self):
        response, runs = await self.send([FENCED])
        self.assertEqual(response.status_code, 200)
        self.assertIn(CODE, response.json()["choices"][0]["message"]["content"])
        self.assertEqual(len(runs[0].calls), 1)
        self.assertNotIn("research", response.json())
        # send() additionally asserts the exact assistant content is persisted once.

    async def test_invalid_code_never_persists_or_becomes_unknown(self):
        response, _ = await self.send(["not code", "not code"])
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "DIRECT_OUTPUT_INVALID")
        self.assertNotIn("choices", response.json())
        self.assertNotIn("UNKNOWN", response.text)
        # send() additionally asserts that persist_chat_exchange was not called.


if __name__ == "__main__":
    unittest.main()

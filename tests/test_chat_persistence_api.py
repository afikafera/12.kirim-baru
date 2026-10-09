"""Disposable-PostgreSQL integration tests for chat persistence API paths.

Run only with ARAN_CHAT_TEST_PGPORT pointed at an isolated disposable database
where migrations/001_create_chat_persistence.sql has already been applied.
"""

import os
import time
import unittest
from contextlib import asynccontextmanager, nullcontext
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from api.auth import hash_password
from memory_manager.backends.postgres import PostgresBackend


TEST_PORT = os.environ.get("ARAN_CHAT_TEST_PGPORT")
if not TEST_PORT:
    raise RuntimeError("ARAN_CHAT_TEST_PGPORT must target disposable PostgreSQL")

TEST_DB_CONFIG = {
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": TEST_PORT,
    "POSTGRES_DB": "aran_chat_test",
    "POSTGRES_USER": "aran_test",
    "POSTGRES_PASSWORD": "aran_test_only",
}
TEST_PASSWORD = "test-only-password-for-chat-persistence"


class TestMemoryManager:
    def __init__(self, _production_config):
        self.pg = PostgresBackend(TEST_DB_CONFIG)
        self.qdrant = None

    def create_conversation(self, *args):
        return self.pg.create_conversation(*args)

    def list_conversations(self, *args):
        return self.pg.list_conversations(*args)

    def get_conversation(self, *args):
        return self.pg.get_conversation(*args)

    def list_messages(self, *args):
        return self.pg.list_messages(*args)

    def create_message(self, *args):
        return self.pg.create_message(*args)

    def persist_chat_exchange(self, **kwargs):
        return self.pg.persist_chat_exchange(**kwargs)


class TestCalibrator:
    def __init__(self, *_args):
        pass


class TestLLM:
    default_model = "deepseek-chat"
    providers = {}

    def __init__(self, *_args):
        pass

    def use_model(self, _model):
        return nullcontext()

    def analyze(self, **_kwargs):
        return {"content": "{}"}


class TestOutcomeLogger:
    def __init__(self, *_args):
        pass


class TestLessonsEngine:
    def __init__(self, *_args):
        pass


class TestHermesAgent:
    def __init__(self, _mm, _cal, llm, _outcome, _lessons):
        self.llm = llm
        self.calls = []

    def research(self, query, context="", attachments=None):
        self.calls.append((query, context, attachments))
        if query == "RAISE_PROVIDER":
            raise RuntimeError("test provider failure")
        if query == "RETURN_NONE":
            return None
        return {"goal": "chat", "answer": f"answer:{query}"}


class FakeLangfuse:
    def start_as_current_observation(self, **_kwargs):
        return nullcontext()


# Import the active route definitions with every database/engine constructor
# redirected to test-only doubles. The only real DB connection uses TEST_DB_CONFIG.
os.environ.update({
    "HERMES_LOGIN_USERNAME": "test-operator",
    "HERMES_LOGIN_USER_ID": "chat-test-owner",
    "HERMES_LOGIN_PASSWORD_HASH": hash_password(TEST_PASSWORD),
    "HERMES_SESSION_COOKIE_SECURE": "false",
    "HERMES_SESSION_TTL_SECONDS": "3600",
})

import calibration.calibrator as calibrator_module
import hermes_agent.orchestrator as orchestrator_module
import lessons_engine.engine as lessons_module
import llm_analyzer.analyzer as llm_module
import memory_manager.manager as manager_module
import outcome_logger.logger as outcome_module

with (
    patch.object(manager_module, "MemoryManager", TestMemoryManager),
    patch.object(calibrator_module, "ConfidenceCalibrator", TestCalibrator),
    patch.object(llm_module, "LLMAnalyzer", TestLLM),
    patch.object(outcome_module, "OutcomeLogger", TestOutcomeLogger),
    patch.object(lessons_module, "LessonsEngine", TestLessonsEngine),
    patch.object(orchestrator_module, "HermesAgent", TestHermesAgent),
):
    import api.main as api_main


class ChatPersistenceApiTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = api_main.app
        cls.mm = api_main.mm
        cls.owner_id = "chat-test-owner"
        cls.fake_langfuse_patch = patch("langfuse.get_client", return_value=FakeLangfuse())
        cls.fake_langfuse_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.fake_langfuse_patch.stop()
        cls.mm.pg.close()

    def setUp(self):
        # This cleanup only touches the explicitly isolated test database.
        with self.mm.pg.conn.cursor() as cur:
            cur.execute("DELETE FROM messages")
            cur.execute("DELETE FROM conversations")

    @asynccontextmanager
    async def make_client(self):
        transport = httpx.ASGITransport(
            app=self.app,
            client=("127.0.0.1", 12345),
            raise_app_exceptions=False,
        )
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            login = await client.post(
                "/auth/login",
                json={"username": "test-operator", "password": TEST_PASSWORD},
            )
            self.assertEqual(login.status_code, 200)
            yield client

    async def test_conversation_endpoints_and_server_identity(self):
        transport = httpx.ASGITransport(app=self.app, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            self.assertEqual((await client.get("/conversations")).status_code, 401)
            login = await client.post(
                "/auth/login",
                json={"username": "test-operator", "password": TEST_PASSWORD},
            )
            self.assertEqual(login.status_code, 200)
            created = await client.post(
                "/conversations",
                json={
                    "title": "  " + "A" * 90 + "  ",
                    "model": "9routerpc",
                    "owner_user_id": "forged-owner",
                },
            )
            self.assertEqual(created.status_code, 200)
            row = created.json()
            self.assertEqual(len(row["title"]), 80)
            self.assertEqual(row["model"], "9routerpc")
            self.assertNotIn("owner_user_id", row)
            self.assertEqual(
                self.mm.pg.get_conversation(self.owner_id, row["id"])["owner_user_id"],
                self.owner_id,
            )
            listed = await client.get("/conversations")
            self.assertEqual([item["id"] for item in listed.json()["data"]], [row["id"]])
            detail = await client.get(f"/conversations/{row['id']}")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["messages"], [])

    async def test_legacy_and_conversation_chat_do_not_duplicate_history(self):
        async with self.make_client() as client:
            first = await client.post(
                "/chat/completions",
                json={"model": "9routerpc", "messages": [
                    {"role": "user", "content": "CHAT_A_TEST"},
                ]},
            )
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["model"], "9routerpc")
            conversation_id = first.json()["conversation_id"]
            first_detail = (await client.get(f"/conversations/{conversation_id}")).json()
            first_updated = first_detail["updated_at"]
            self.assertEqual(
                [(item["role"], item["content"]) for item in first_detail["messages"]],
                [("user", "CHAT_A_TEST"), ("assistant", "answer:CHAT_A_TEST")],
            )

            second = await client.post(
                "/chat/completions",
                json={
                    "conversation_id": conversation_id,
                    "model": "deepseek-chat",
                    "user_id": "forged-owner",
                    "messages": [
                        {"role": "user", "content": "CHAT_A_TEST"},
                        {"role": "assistant", "content": "answer:CHAT_A_TEST"},
                        {"role": "user", "content": "CHAT_A_SECOND"},
                    ],
                },
            )
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json()["conversation_id"], conversation_id)
            detail = await client.get(f"/conversations/{conversation_id}")
            self.assertEqual(detail.status_code, 200)
            chat = detail.json()
            self.assertEqual(chat["model"], "deepseek-chat")
            self.assertNotEqual(chat["updated_at"], first_updated)
            self.assertEqual(
                [(item["role"], item["content"]) for item in chat["messages"]],
                [
                    ("user", "CHAT_A_TEST"),
                    ("assistant", "answer:CHAT_A_TEST"),
                    ("user", "CHAT_A_SECOND"),
                    ("assistant", "answer:CHAT_A_SECOND"),
                ],
            )
            self.assertEqual(len(api_main.hermes.calls), 2)
            self.assertIn("CHAT_A_TEST", api_main.hermes.calls[1][1])

    async def test_post_created_conversation_gets_first_message_title(self):
        async with self.make_client() as client:
            created = await client.post(
                "/conversations", json={"title": "New Chat", "model": "9routerpc"}
            )
            self.assertEqual(created.status_code, 200)
            conversation_id = created.json()["id"]
            response = await client.post(
                "/chat/completions",
                json={
                    "conversation_id": conversation_id,
                    "model": "9routerpc",
                    "messages": [{"role": "user", "content": "First message title"}],
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            detail = await client.get(f"/conversations/{conversation_id}")
            self.assertEqual(detail.json()["title"], "First message title")

    def test_create_message_updates_timestamp_and_preserves_json_content(self):
        conversation = self.mm.create_conversation(
            self.owner_id, "Direct create_message", "deepseek-chat"
        )
        initial_updated_at = conversation["updated_at"]
        time.sleep(0.002)
        self.mm.create_message(conversation["id"], "user", "plain content")
        self.mm.create_message(
            conversation["id"], "assistant", [{"type": "text", "text": "array"}]
        )
        self.mm.create_message(
            conversation["id"], "assistant", {"text": "object"}
        )
        messages = self.mm.list_messages(self.owner_id, conversation["id"])
        self.assertEqual(
            [message["role"] for message in messages],
            ["user", "assistant", "assistant"],
        )
        self.assertEqual(messages[0]["content"], "plain content")
        self.assertEqual(messages[1]["content"][0]["text"], "array")
        self.assertEqual(messages[2]["content"]["text"], "object")
        refreshed = self.mm.get_conversation(self.owner_id, conversation["id"])
        self.assertGreater(refreshed["updated_at"], initial_updated_at)

    async def test_foreign_and_invalid_conversation_ids_are_hidden(self):
        foreign = self.mm.create_conversation("another-test-user", "Foreign", "9routerpc")
        async with self.make_client() as client:
            self.assertEqual(
                (await client.get(f"/conversations/{foreign['id']}")).status_code,
                404,
            )
            response = await client.post(
                "/chat/completions",
                json={
                    "conversation_id": str(foreign["id"]),
                    "messages": [{"role": "user", "content": "must not run"}],
                },
            )
            self.assertEqual(response.status_code, 404)
            invalid = await client.get("/conversations/not-a-uuid")
            self.assertEqual(invalid.status_code, 404)
            invalid_chat = await client.post(
                "/chat/completions",
                json={
                    "conversation_id": "not-a-uuid",
                    "messages": [{"role": "user", "content": "must not run"}],
                },
            )
            self.assertEqual(invalid_chat.status_code, 404)
            self.assertEqual(len(api_main.hermes.calls), 0)

    async def test_provider_failure_does_not_persist_partial_exchange(self):
        async with self.make_client() as client:
            response = await client.post(
                "/chat/completions",
                json={"messages": [{"role": "user", "content": "RAISE_PROVIDER"}]},
            )
            self.assertEqual(response.status_code, 500)
            self.assertEqual(self.mm.list_conversations(self.owner_id), [])

    async def test_none_result_is_not_saved_as_fake_assistant(self):
        async with self.make_client() as client:
            response = await client.post(
                "/chat/completions",
                json={"messages": [{"role": "user", "content": "RETURN_NONE"}]},
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("conversation_id", response.json())
            self.assertEqual(self.mm.list_conversations(self.owner_id), [])

    def test_transaction_rolls_back_partial_exchange_on_db_failure(self):
        with self.assertRaises(Exception):
            self.mm.persist_chat_exchange(
                owner_user_id=self.owner_id,
                conversation_id=None,
                title="Rollback test",
                model="deepseek-chat",
                user_content="would be first insert",
                assistant_content=object(),
            )
        self.assertEqual(self.mm.list_conversations(self.owner_id), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

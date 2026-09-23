import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from llm_analyzer.analyzer import LLMAnalyzer


class TestLLMAnalyzerContentNull(unittest.TestCase):

    def setUp(self):
        self.config = {
            "LLM_PROVIDER_TEST_API_KEY": "fake_key",
            "LLM_PROVIDER_TEST_BASE_URL": "https://api.fake.test/v1",
            "LLM_PROVIDER_TEST_MODEL": "test-provider/test-model",
            "LLM_DEFAULT_MODEL": "test",
        }
        self.analyzer = LLMAnalyzer(self.config)

    @patch("llm_analyzer.analyzer.OpenAI")
    def test_content_none_raises_runtime_error(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        # Simulasi reasoning model mengembalikan choices dengan message.content = None
        fake_message = SimpleNamespace(content=None)
        fake_choice = SimpleNamespace(message=fake_message, finish_reason="stop")
        fake_response = SimpleNamespace(
            choices=[fake_choice],
            model="test-provider/test-model",
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        mock_client.chat.completions.create.return_value = fake_response

        with self.assertRaises(RuntimeError) as ctx:
            self.analyzer.analyze(
                system_prompt="system",
                user_query="user query",
            )

        self.assertIn("returned null content in message", str(ctx.exception))

    @patch("llm_analyzer.analyzer.OpenAI")
    def test_choices_empty_raises_runtime_error(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        fake_response = SimpleNamespace(
            choices=[],
            model="test-provider/test-model",
            usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
        )
        mock_client.chat.completions.create.return_value = fake_response

        with self.assertRaises(RuntimeError) as ctx:
            self.analyzer.analyze(
                system_prompt="system",
                user_query="user query",
            )

        self.assertIn("returned empty or null choices", str(ctx.exception))

    @patch("llm_analyzer.analyzer.OpenAI")
    def test_message_none_raises_runtime_error(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        fake_choice = SimpleNamespace(message=None, finish_reason="stop")
        fake_response = SimpleNamespace(
            choices=[fake_choice],
            model="test-provider/test-model",
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        mock_client.chat.completions.create.return_value = fake_response

        with self.assertRaises(RuntimeError) as ctx:
            self.analyzer.analyze(
                system_prompt="system",
                user_query="user query",
            )

        self.assertIn("returned null content in message", str(ctx.exception))

    @patch("llm_analyzer.analyzer.OpenAI")
    def test_valid_content_returns_dict(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        fake_message = SimpleNamespace(content="Successful generation")
        fake_choice = SimpleNamespace(message=fake_message, finish_reason="stop")
        fake_response = SimpleNamespace(
            choices=[fake_choice],
            model="test-provider/test-model",
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        mock_client.chat.completions.create.return_value = fake_response

        result = self.analyzer.analyze(
            system_prompt="system",
            user_query="user query",
        )

        self.assertEqual(result["content"], "Successful generation")
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["tokens_input"], 10)
        self.assertEqual(result["tokens_output"], 5)


if __name__ == "__main__":
    unittest.main()

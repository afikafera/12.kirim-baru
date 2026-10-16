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


    @patch("llm_analyzer.analyzer.OpenAI")
    def test_selected_provider_reaches_upstream_model(self, mock_openai_cls):
        config = {
            "LLM_DEFAULT_MODEL": "default",
            "LLM_PROVIDER_DEFAULT_API_KEY": "default-test-key",
            "LLM_PROVIDER_DEFAULT_BASE_URL": "https://default.invalid/v1",
            "LLM_PROVIDER_DEFAULT_MODEL": "vendor/default-upstream",
            "LLM_PROVIDER_POOLSIDE_API_KEY": "poolside-test-key",
            "LLM_PROVIDER_POOLSIDE_BASE_URL": "https://poolside.invalid/v1",
            "LLM_PROVIDER_POOLSIDE_MODEL": "poolside/laguna-s-2.1",
        }
        analyzer = LLMAnalyzer(config)
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="OK"),
                finish_reason="stop",
            )],
            model="poolside/laguna-s-2.1",
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

        with analyzer.use_model("poolside"):
            result = analyzer.analyze("system", "hello")

        self.assertEqual(result["content"], "OK")
        self.assertEqual(
            mock_client.chat.completions.create.call_args.kwargs["model"],
            "poolside/laguna-s-2.1",
        )
        self.assertEqual(
            mock_openai_cls.call_args.kwargs["api_key"],
            "poolside-test-key",
        )


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from api.model_registry import models_response
from llm_analyzer.analyzer import LLMAnalyzer


class ModelRegistryTests(unittest.TestCase):
    def _provider(self, name, upstream):
        return {
            f"LLM_PROVIDER_{name}_API_KEY": "registry-test-secret",
            f"LLM_PROVIDER_{name}_BASE_URL": "https://example.invalid/v1",
            f"LLM_PROVIDER_{name}_MODEL": upstream,
        }

    def test_multiple_configured_models_are_listed_without_secrets(self):
        config = {}
        config.update(self._provider("OMNIROUTE", "route/omni"))
        config.update(self._provider("POOLSIDE", "poolside/laguna"))
        config.update(self._provider("9ROUTERPC", "route/free"))
        analyzer = LLMAnalyzer(config)

        response = models_response(analyzer.providers)
        self.assertEqual(
            [item["id"] for item in response["data"]],
            ["9routerpc", "omniroute", "poolside"],
        )
        self.assertEqual(response["object"], "list")
        self.assertTrue(all(item["object"] == "model" for item in response["data"]))
        self.assertNotIn("registry-test-secret", json.dumps(response))

    def test_adding_provider_adds_one_model(self):
        config = {}
        config.update(self._provider("OMNIROUTE", "route/omni"))
        config.update(self._provider("POOLSIDE", "poolside/laguna"))
        config.update(self._provider("9ROUTERPC", "route/free"))
        three_models = models_response(LLMAnalyzer(config).providers)
        config.update(self._provider("DEEPSEEK-CHAT", "deepseek-chat"))
        four_models = models_response(LLMAnalyzer(config).providers)

        self.assertEqual(len(three_models["data"]), 3)
        self.assertEqual(len(four_models["data"]), 4)
        self.assertIn("deepseek-chat", [item["id"] for item in four_models["data"]])

    def test_empty_and_incomplete_registry_is_empty(self):
        empty = LLMAnalyzer({})
        incomplete = LLMAnalyzer({
            "LLM_PROVIDER_UNUSED_BASE_URL": "https://example.invalid/v1",
        })
        self.assertEqual(models_response(empty.providers)["data"], [])
        self.assertEqual(models_response(incomplete.providers)["data"], [])

    def test_provider_aliases_trim_and_deduplicate(self):
        config = self._provider("OMNIROUTE", "route/omni")
        config["LLM_PROVIDER_OMNIROUTE_ALIASES"] = " alias ,,alias, "
        analyzer = LLMAnalyzer(config)
        self.assertEqual(analyzer.providers["omniroute"]["aliases"], {"alias"})
        self.assertEqual(
            [item["id"] for item in models_response(analyzer.providers)["data"]],
            ["omniroute"],
        )

    def test_hyphenated_provider_name_is_supported(self):
        config = self._provider("DEEPSEEK-CHAT", "deepseek-chat")
        analyzer = LLMAnalyzer(config)
        self.assertEqual(
            [item["id"] for item in models_response(analyzer.providers)["data"]],
            ["deepseek-chat"],
        )
        provider_name, provider = analyzer._get_provider("deepseek-chat")
        self.assertEqual(provider_name, "deepseek-chat")
        self.assertEqual(provider["model"], "deepseek-chat")

    def test_unknown_model_is_rejected_by_provider_registry(self):
        analyzer = LLMAnalyzer(self._provider("POOLSIDE", "poolside/upstream"))
        with self.assertRaisesRegex(ValueError, "Unknown LLM model/provider"):
            analyzer._get_provider("not-configured")


if __name__ == "__main__":
    unittest.main()

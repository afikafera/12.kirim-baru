import json
import unittest

from hermes_agent.fact_checker import FactChecker


class MockLLM:
    def __init__(self, response_text: str):
        self.response_text = response_text

    def analyze(
        self,
        system_prompt,
        user_query,
        temperature=0.1,
        max_tokens=None,
    ):
        return {
            "content": self.response_text,
            "tokens_input": 100,
            "tokens_output": 50,
            "api_cost": 0.001,
            "finish_reason": "stop",
        }


class TestExtractionNormalizerRegression(unittest.TestCase):
    def setUp(self):
        self.evidence = [{
            "url": "https://www.coingecko.com/en/coins/ethereum",
            "source_type": "official_docs",
            "content": (
                "Price: $2400.5 USD\n"
                "Last updated: 2026-09-16T13:30:20+00:00"
            ),
        }]

        self.checklist = [{
            "field_id": "req_1",
            "label": "Ethereum current price",
        }]

    def test_case_1_target_trace_list_flat_dicts(self):
        llm_json = json.dumps([
            {
                "source_url": "https://www.coingecko.com/en/coins/ethereum",
                "source_type": "official_docs",
                "ethereum_current_price": "$2400.5 USD",
            },
            {
                "source_url": "https://www.coingecko.com/en/coins/ethereum",
                "source_type": "official_docs",
                "ethereum_last_updated": "2026-09-16T13:30:20+00:00",
            },
        ])

        checker = FactChecker(llm_analyzer=MockLLM(llm_json))
        facts, _ = checker.extract_facts_batch(
            self.evidence,
            self.checklist,
        )

        self.assertIn("ethereum_current_price", facts)
        self.assertIn("ethereum_last_updated", facts)
        self.assertEqual(
            facts["ethereum_current_price"]["value"],
            "$2400.5 USD",
        )

    def test_case_2_existing_field_id_format_preserved(self):
        llm_json = json.dumps([
            {
                "field_id": "ethereum_current_price",
                "value": "$2400.5 USD",
                "source": "https://www.coingecko.com/en/coins/ethereum",
                "source_type": "official_docs",
            }
        ])

        checker = FactChecker(llm_analyzer=MockLLM(llm_json))
        facts, _ = checker.extract_facts_batch(
            self.evidence,
            self.checklist,
        )

        self.assertIn("ethereum_current_price", facts)
        self.assertEqual(
            facts["ethereum_current_price"]["value"],
            "$2400.5 USD",
        )

    def test_case_3_existing_id_value_format_preserved(self):
        llm_json = json.dumps([
            {
                "id": "ethereum_current_price",
                "value": "$2400.5 USD",
                "source": "https://www.coingecko.com/en/coins/ethereum",
                "source_type": "official_docs",
            }
        ])

        checker = FactChecker(llm_analyzer=MockLLM(llm_json))
        facts, _ = checker.extract_facts_batch(
            self.evidence,
            self.checklist,
        )

        self.assertIn("ethereum_current_price", facts)
        self.assertEqual(
            facts["ethereum_current_price"]["value"],
            "$2400.5 USD",
        )

    def test_case_4_existing_single_key_format_preserved(self):
        llm_json = json.dumps([
            {
                "ethereum_current_price": "$2400.5 USD"
            }
        ])

        checker = FactChecker(llm_analyzer=MockLLM(llm_json))
        facts, _ = checker.extract_facts_batch(
            self.evidence,
            self.checklist,
        )

        self.assertIn("ethereum_current_price", facts)
        self.assertEqual(
            facts["ethereum_current_price"]["value"],
            "$2400.5 USD",
        )

    def test_case_5_existing_root_dictionary_preserved(self):
        llm_json = json.dumps({
            "ethereum_current_price": {
                "value": "$2400.5 USD",
                "source": "https://www.coingecko.com/en/coins/ethereum",
                "source_type": "official_docs",
            }
        })

        checker = FactChecker(llm_analyzer=MockLLM(llm_json))
        facts, _ = checker.extract_facts_batch(
            self.evidence,
            self.checklist,
        )

        self.assertIn("ethereum_current_price", facts)
        self.assertEqual(
            facts["ethereum_current_price"]["value"],
            "$2400.5 USD",
        )

    def test_case_6_provenance_guard_rejects_fake_url_in_list(self):
        llm_json = json.dumps([
            {
                "source_url": "https://fake-scam-crypto.com/eth",
                "source_type": "official_docs",
                "price": "$2400.5 USD",
            }
        ])

        checker = FactChecker(llm_analyzer=MockLLM(llm_json))
        facts, _ = checker.extract_facts_batch(
            self.evidence,
            self.checklist,
        )

        self.assertEqual(facts, {})

    def test_case_7_flat_list_and_structured_dict_without_value_key_preserved(self):
        code_url = "https://github.com/afikafera/12.kirim-baru/blob/master/aran_search/searcher.py"
        code_evidence = [{
            "url": code_url,
            "source_type": "official_docs",
            "content": (
                "import asyncio\nfrom curl_cffi import requests as cffi_requests\n"
                "class AranSearcher:\n"
                "    ENABLE_QUERY_REFINEMENT = False\n"
                "    SUBDOMAIN_RULES = {'docs': 3, 'developer': 3}\n"
                "    def fetch_url(self, url: str) -> str:\n"
                "        '''Fetch single URL content via cascade: Jina Reader -> Tavily Extract -> Exa -> Camoufox'''\n"
            ),
        }]
        llm_json = json.dumps({
            "source_url": code_url,
            "source_type": "official_docs",
            "class_name": "AranSearcher",
            "imports": ["import asyncio", "from curl_cffi import requests as cffi_requests"],
            "external_dependencies": ["curl_cffi"],
            "class_constant_subdomain_rules": {"docs": 3, "developer": 3},
            "method_fetch_url": {
                "signature": "def fetch_url(self, url: str) -> str",
                "docstring": "Fetch single URL content via cascade: Jina Reader -> Tavily Extract -> Exa -> Camoufox",
            },
            "class_constants_enable_query_refinement": {
                "value": False,
                "source": code_url,
                "source_type": "official_docs",
            },
        })

        checker = FactChecker(llm_analyzer=MockLLM(llm_json))
        facts, _ = checker.extract_facts_batch(code_evidence, self.checklist)

        self.assertIn("class_name", facts)
        self.assertIn("imports", facts)
        self.assertEqual(
            facts["imports"]["value"],
            ["import asyncio", "from curl_cffi import requests as cffi_requests"],
        )
        self.assertIn("external_dependencies", facts)
        self.assertIn("class_constant_subdomain_rules", facts)
        self.assertEqual(
            facts["class_constant_subdomain_rules"]["value"],
            {"docs": 3, "developer": 3},
        )
        self.assertIn("method_fetch_url", facts)
        self.assertEqual(
            facts["method_fetch_url"]["value"]["signature"],
            "def fetch_url(self, url: str) -> str",
        )
        self.assertIn("class_constants_enable_query_refinement", facts)
        self.assertEqual(
            facts["class_constants_enable_query_refinement"]["value"],
            "False",
        )

    def test_case_8_provenance_guard_rejects_unverified_list_and_structured_dict(self):
        llm_json = json.dumps({
            "source_url": "https://fake-scam-crypto.com/searcher.py",
            "source_type": "official_docs",
            "imports": ["import os"],
            "method_fetch_url": {
                "signature": "def fetch_url(self, url: str) -> str",
            },
        })

        checker = FactChecker(llm_analyzer=MockLLM(llm_json))
        facts, _ = checker.extract_facts_batch(self.evidence, self.checklist)
        self.assertEqual(facts, {})


if __name__ == "__main__":
    unittest.main()

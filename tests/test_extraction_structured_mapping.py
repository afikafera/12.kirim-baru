"""Regressions for sourced scalar-leaf mappings and downstream validation."""

import copy
import json
import unittest
from unittest.mock import patch

from hermes_agent import fact_checker as extraction


URL = "https://example.test/source.py"
CONTENT = (
    "class Widget: OPEN = False; LIMIT = 0; "
    "SUBDOMAIN_RULES = {'docs': 3, 'developer': 3}; "
    "def fetch_url(self, url: str) -> str: "
    "Fetch a single URL using the documented cascade."
)
EVIDENCE = [{"url": URL, "source_type": "official_docs", "content": CONTENT}]


class StubLLM:
    def __init__(self, payload):
        self.payload = payload

    def analyze(self, *args, **kwargs):
        return {"content": json.dumps(self.payload), "finish_reason": "stop",
                "tokens_input": 0, "tokens_output": 0, "api_cost": 0}


class ExtractionStructuredMappingTests(unittest.TestCase):
    def payload(self, value, source=URL):
        return {"source_url": source, "source_type": "official_docs", "rules": value}

    def extract(self, payload):
        return extraction.FactChecker(StubLLM(payload)).extract_facts_batch(
            EVIDENCE, [{"field_id": "rules", "label": "Source code facts"}]
        )[0]

    def test_supported_numeric_mapping_preserves_parent(self):
        value = {"docs": 3, "developer": 3}
        normalized = extraction._normalize_extraction_kvs(self.payload(value), EVIDENCE)
        self.assertEqual(set(normalized), {"rules"})
        self.assertEqual(normalized["rules"]["value"], value)
        self.assertEqual(normalized["rules"]["source"], URL)
        self.assertEqual(self.extract(self.payload(value))["rules"]["value"], value)

    def test_structured_method_mapping_is_preserved(self):
        value = {"signature": "def fetch_url(self, url: str) -> str",
                 "docstring": "Fetch a single URL using the documented cascade."}
        facts = self.extract(self.payload(value))
        self.assertEqual(set(facts), {"rules"})
        self.assertEqual(facts["rules"]["value"], value)

    def test_unsupported_numbers_are_rejected_downstream(self):
        value = {"docs": 987654, "developer": 987654}
        payload = self.payload(value)
        normalized = extraction._normalize_extraction_kvs(payload, EVIDENCE)
        self.assertEqual(normalized["rules"]["value"], value)
        with patch.object(extraction, "classify_value_support",
                          wraps=extraction.classify_value_support) as numeric_guard:
            facts = self.extract(payload)
        numeric_guard.assert_any_call(str(value), CONTENT)
        self.assertNotIn("rules", facts)

    def test_invalid_root_source_is_rejected(self):
        payload = self.payload({"docs": 3}, "https://unverified.test/source.py")
        self.assertEqual(extraction._normalize_extraction_kvs(payload, EVIDENCE), {})
        self.assertEqual(self.extract(payload), {})

    def test_invalid_child_source_is_not_replaced_with_root_source(self):
        payload = self.payload({"docs": 3, "source": "https://unverified.test/source.py"})
        self.assertEqual(extraction._normalize_extraction_kvs(payload, EVIDENCE), {})
        self.assertEqual(self.extract(payload), {})

    def test_canonical_value_and_description_facts_keep_their_shape(self):
        payload = {"value_fact": {"value": {"docs": 3}, "source": URL},
                   "description_fact": {"description": "Documented behavior.", "source": URL}}
        normalized = extraction._normalize_extraction_kvs(payload, EVIDENCE)
        self.assertEqual(normalized["value_fact"]["value"], {"docs": 3})
        self.assertEqual(normalized["description_fact"]["value"], "Documented behavior.")

    def test_nested_wrapper_still_recurses_into_canonical_facts(self):
        payload = {"wrapper": {"count": {"value": 3, "source": URL}}}
        normalized = extraction._normalize_extraction_kvs(payload, EVIDENCE)
        self.assertEqual(set(normalized), {"count"})
        self.assertEqual(normalized["count"]["value"], 3)

    def test_nested_metadata_wrapper_is_not_promoted(self):
        payload = {"wrapper": {"metadata": {"title": "Source page", "url": URL}}}
        self.assertEqual(extraction._normalize_extraction_kvs(payload, EVIDENCE), {})

    def test_facts_container_still_recurses(self):
        payload = {"source_url": URL, "facts": {"count": 3}}
        normalized = extraction._normalize_extraction_kvs(payload, EVIDENCE)
        self.assertEqual(set(normalized), {"count"})
        self.assertEqual(normalized["count"]["value"], 3)

    def test_empty_mapping_is_not_promoted(self):
        self.assertEqual(extraction._normalize_extraction_kvs(self.payload({}), EVIDENCE), {})

    def test_scalar_types_and_original_input_are_preserved(self):
        value = {"open": False, "limit": 0, "label": "003"}
        payload = self.payload(value)
        original = copy.deepcopy(payload)
        normalized = extraction._normalize_extraction_kvs(payload, EVIDENCE)
        self.assertEqual(normalized["rules"]["value"], value)
        self.assertIs(normalized["rules"]["value"]["open"], False)
        self.assertIsInstance(normalized["rules"]["value"]["limit"], int)
        self.assertEqual(payload, original)


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace

from hermes_agent.coverage_evaluator import (
    CoverageEvaluator,
    CoverageResult,
)


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class CoverageEvaluatorTests(unittest.TestCase):

    def setUp(self):
        self.section = SimpleNamespace(
            section_id="S001",
            must_cover=[
                "arsitektur",
                "routing",
                "recovery",
            ],
        )

    def test_all_targets_covered(self):
        llm = FakeLLM({
            "covered": ["arsitektur", "routing", "recovery"],
            "remaining": [],
            "semantic_complete": True,
            "reason": "all targets covered",
        })

        result = CoverageEvaluator(llm).evaluate(
            self.section,
            "output",
            {"facts": "evidence"},
        )

        self.assertEqual(
            result,
            CoverageResult(
                ["arsitektur", "routing", "recovery"],
                [],
                True,
                "all targets covered",
            ),
        )

    def test_partial_coverage(self):
        llm = FakeLLM({
            "covered": ["arsitektur"],
            "remaining": ["routing", "recovery"],
            "semantic_complete": False,
            "reason": "two targets missing",
        })

        result = CoverageEvaluator(llm).evaluate(
            self.section,
            "output",
        )

        self.assertEqual(result.covered_items, ["arsitektur"])
        self.assertEqual(
            result.remaining_items,
            ["routing", "recovery"],
        )
        self.assertFalse(result.semantic_complete)

    def test_empty_output(self):
        result = CoverageEvaluator(FakeLLM({})).evaluate(
            self.section,
            "",
        )

        self.assertEqual(result.covered_items, [])
        self.assertEqual(
            result.remaining_items,
            self.section.must_cover,
        )
        self.assertFalse(result.semantic_complete)
        self.assertEqual(result.reason, "empty_output")

    def test_empty_targets(self):
        section = SimpleNamespace(must_cover=[])

        result = CoverageEvaluator(FakeLLM({})).evaluate(
            section,
            "output",
        )

        self.assertEqual(result.covered_items, [])
        self.assertEqual(result.remaining_items, [])
        self.assertTrue(result.semantic_complete)

    def test_evaluator_unavailable(self):
        result = CoverageEvaluator(None).evaluate(
            self.section,
            "output",
        )

        self.assertEqual(result.covered_items, [])
        self.assertEqual(
            result.remaining_items,
            self.section.must_cover,
        )
        self.assertIsNone(result.semantic_complete)

    def test_unknown_items_are_not_added(self):
        llm = FakeLLM({
            "covered": ["arsitektur", "unknown"],
            "remaining": ["routing", "recovery", "unknown"],
            "semantic_complete": True,
            "reason": "test",
        })

        result = CoverageEvaluator(llm).evaluate(
            self.section,
            "output",
        )

        self.assertEqual(result.covered_items, ["arsitektur"])
        self.assertEqual(
            result.remaining_items,
            ["routing", "recovery"],
        )

    def test_llm_claim_complete_cannot_override_remaining(self):
        llm = FakeLLM({
            "covered": ["arsitektur"],
            "remaining": [],
            "semantic_complete": True,
            "reason": "incorrect complete claim",
        })

        result = CoverageEvaluator(llm).evaluate(
            self.section,
            "output",
        )

        self.assertEqual(result.covered_items, ["arsitektur"])
        self.assertEqual(
            result.remaining_items,
            ["routing", "recovery"],
        )
        self.assertFalse(result.semantic_complete)

    def test_llm_claim_incomplete_cannot_override_no_remaining(self):
        llm = FakeLLM({
            "covered": ["arsitektur", "routing", "recovery"],
            "remaining": [],
            "semantic_complete": False,
            "reason": "incorrect incomplete claim",
        })

        result = CoverageEvaluator(llm).evaluate(
            self.section,
            "output",
        )

        self.assertTrue(result.semantic_complete)
        self.assertEqual(result.remaining_items, [])

    def test_coverage_invariants(self):
        llm = FakeLLM({
            "covered": ["routing", "arsitektur"],
            "remaining": ["recovery"],
            "semantic_complete": False,
            "reason": "partial",
        })

        result = CoverageEvaluator(llm).evaluate(
            self.section,
            "output",
        )

        self.assertEqual(
            set(result.covered_items) | set(result.remaining_items),
            set(self.section.must_cover),
        )
        self.assertEqual(
            set(result.covered_items) & set(result.remaining_items),
            set(),
        )

    def test_facts_are_passed_as_context_not_output(self):
        llm = FakeLLM({
            "covered": ["arsitektur"],
            "remaining": ["routing", "recovery"],
            "semantic_complete": False,
            "reason": "partial",
        })

        CoverageEvaluator(llm).evaluate(
            self.section,
            "output",
            {"routing": "fact exists"},
        )

        self.assertEqual(len(llm.calls), 1)
        self.assertIn(
            "fact exists",
            llm.calls[0]["user_query"],
        )


if __name__ == "__main__":
    unittest.main()

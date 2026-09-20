import unittest

from hermes_agent.output_manifest import OutcomeType
from hermes_agent.outcome_classifier import OutcomeClassifier


class TestOutcomeClassifier(unittest.TestCase):

    def test_complete_clean_response(self):
        result = {
            "content": "Valid section output.",
            "finish_reason": "stop",
        }

        self.assertEqual(
            OutcomeClassifier.classify(result),
            OutcomeType.COMPLETE,
        )

    def test_length_becomes_truncated(self):
        result = {
            "content": "Partial section output",
            "finish_reason": "length",
        }

        self.assertEqual(
            OutcomeClassifier.classify(result),
            OutcomeType.TRUNCATED,
        )

    def test_empty_content_is_structurally_invalid(self):
        result = {
            "content": "",
            "finish_reason": "stop",
        }

        self.assertEqual(
            OutcomeClassifier.classify(result),
            OutcomeType.STRUCTURALLY_INVALID,
        )

    def test_none_content_is_structurally_invalid(self):
        result = {
            "content": None,
            "finish_reason": "stop",
        }

        self.assertEqual(
            OutcomeClassifier.classify(result),
            OutcomeType.STRUCTURALLY_INVALID,
        )

    def test_invalid_content_type_is_structurally_invalid(self):
        result = {
            "content": {"unexpected": "object"},
            "finish_reason": "stop",
        }

        self.assertEqual(
            OutcomeClassifier.classify(result),
            OutcomeType.STRUCTURALLY_INVALID,
        )

    def test_provider_exception(self):
        result = {
            "content": "irrelevant",
            "finish_reason": "stop",
        }

        self.assertEqual(
            OutcomeClassifier.classify(
                result,
                exception=RuntimeError("provider unavailable"),
            ),
            OutcomeType.PROVIDER_FAILURE,
        )

    def test_semantic_incomplete_requires_explicit_signal(self):
        result = {
            "content": "Valid but incomplete section.",
            "finish_reason": "stop",
        }

        self.assertEqual(
            OutcomeClassifier.classify(
                result,
                semantic_complete=False,
            ),
            OutcomeType.SEMANTICALLY_INCOMPLETE,
        )

    def test_semantic_unknown_does_not_fail(self):
        result = {
            "content": "Valid section output.",
            "finish_reason": "stop",
        }

        self.assertEqual(
            OutcomeClassifier.classify(
                result,
                semantic_complete=None,
            ),
            OutcomeType.COMPLETE,
        )

    def test_no_progress(self):
        result = {
            "content": "Same output as before.",
            "finish_reason": "stop",
        }

        self.assertEqual(
            OutcomeClassifier.classify(
                result,
                no_progress=True,
            ),
            OutcomeType.NO_PROGRESS,
        )

    def test_no_progress_precedes_semantic_signal(self):
        result = {
            "content": "Same output as before.",
            "finish_reason": "stop",
        }

        self.assertEqual(
            OutcomeClassifier.classify(
                result,
                no_progress=True,
                semantic_complete=False,
            ),
            OutcomeType.NO_PROGRESS,
        )

    def test_exception_precedes_other_signals(self):
        result = {
            "content": "ignored",
            "finish_reason": "length",
        }

        self.assertEqual(
            OutcomeClassifier.classify(
                result,
                exception=RuntimeError("provider unavailable"),
                no_progress=True,
                semantic_complete=False,
            ),
            OutcomeType.PROVIDER_FAILURE,
        )


if __name__ == "__main__":
    unittest.main()

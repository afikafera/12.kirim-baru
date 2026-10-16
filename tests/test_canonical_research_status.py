import logging
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
import test_attachment_fact_extraction_failures as attachment_harness
from test_attachment_fact_extraction_failures import URL
from hermes_agent.output_aggregator import AggregatedOutput, OutputAggregator
from hermes_agent.output_manifest import ScalerStatus
from hermes_agent.research_status import build_research_metadata


VALID_EXTRACTION = {
    "content": '{"nominal_impedance":{"value":"8 ohm","source":"%s","source_type":"official_docs"}}' % URL,
    "finish_reason": "stop",
    "tokens_input": 1,
    "tokens_output": 1,
}


def aggregate_with(status):
    return AggregatedOutput(
        content="synthetic aggregate",
        sections_total=1,
        sections_final=1 if status == ScalerStatus.DONE else 0,
        sections_degraded=1 if status == ScalerStatus.PARTIAL else 0,
        sections_failed=1 if status == ScalerStatus.FAILED else 0,
        total_tokens_used=1,
        scaler_status=status,
    )


class CanonicalResearchStatusTests(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._previous_logging_disable = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, self._previous_logging_disable)

    def run_success(self, scaler_status):
        harness = attachment_harness.AttachmentFactExtractionFailureBaselineTests()
        with patch.object(OutputAggregator, "aggregate", return_value=aggregate_with(scaler_status)):
            outcome = harness._run_research([VALID_EXTRACTION])
        self.assertIsNone(outcome["escaped"])
        self.assertGreater(outcome["result"]["facts_count"], 0)
        return outcome["result"]

    def test_done_requirements_and_done_aggregator(self):
        result = self.run_success(ScalerStatus.DONE)
        self.assertEqual(result["research_status"], "DONE")
        self.assertEqual(result["research"]["status"], "DONE")
        self.assertEqual(result["research"]["aggregator_status"], "DONE")

    def test_partial_aggregator_overrides_requirement_done(self):
        result = self.run_success(ScalerStatus.PARTIAL)
        self.assertEqual(result["research_status"], "DONE")
        self.assertEqual(result["research"]["status"], "PARTIAL")
        self.assertTrue(result["research"]["degraded"])

    def test_failed_aggregator_overrides_requirement_done(self):
        result = self.run_success(ScalerStatus.FAILED)
        self.assertEqual(result["research_status"], "DONE")
        self.assertEqual(result["research"]["status"], "FAILED")

    def test_done_without_aggregator_confirmation_is_not_done(self):
        result = build_research_metadata("DONE", 1, {}, None)
        self.assertEqual(result["status"], "PARTIAL")

    def test_incomplete_requirement_is_partial_even_if_aggregate_done(self):
        result = build_research_metadata("INCOMPLETE", 1, {}, ScalerStatus.DONE)
        self.assertEqual(result["status"], "PARTIAL")

    def test_orchestrator_provider_exhausted_return_has_canonical_failure(self):
        harness = attachment_harness.AttachmentFactExtractionFailureBaselineTests()
        outcome = harness._run_research([
            RuntimeError("HTTP 400 Model is unavailable"),
            RuntimeError("HTTP 400 Model is unavailable"),
        ])
        self.assertIsNone(outcome["escaped"])
        self.assertEqual(outcome["result"]["research"]["status"], "FAILED")
        self.assertEqual(outcome["result"]["research"]["status_detail"], "PROVIDER_EXHAUSTED")
        self.assertIsNone(outcome["result"]["research"]["aggregator_status"])

    def test_orchestrator_worker_invalid_return_has_canonical_failure(self):
        harness = attachment_harness.AttachmentFactExtractionFailureBaselineTests()
        outcome = harness._run_research([
            {"content": "Markdown prose, not JSON.", "finish_reason": "stop"},
            {"content": "Still prose, not JSON.", "finish_reason": "stop"},
        ])
        self.assertIsNone(outcome["escaped"])
        self.assertEqual(outcome["result"]["research"]["status"], "FAILED")
        self.assertEqual(outcome["result"]["research"]["status_detail"], "WORKER_OUTPUT_INVALID")

    def test_provider_exhausted_is_failed_with_detail(self):
        result = build_research_metadata("PROVIDER_EXHAUSTED", 0, {}, None)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["status_detail"], "PROVIDER_EXHAUSTED")
        self.assertEqual(result["failure_class"], "PROVIDER_EXHAUSTED")

    def test_worker_output_invalid_is_failed(self):
        result = build_research_metadata("WORKER_OUTPUT_INVALID", 0, {}, None)
        self.assertEqual(result["status"], "FAILED")

    def test_truncated_output_unusable_is_failed(self):
        result = build_research_metadata("TRUNCATED_OUTPUT_UNUSABLE", 0, {}, None)
        self.assertEqual(result["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()

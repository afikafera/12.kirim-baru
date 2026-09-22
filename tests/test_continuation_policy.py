import unittest
from types import SimpleNamespace

from hermes_agent.continuation_policy import (
    ContinuationDecision,
    ContinuationPolicy,
)
from hermes_agent.coverage_evaluator import CoverageResult
from hermes_agent.output_manifest import (
    OutcomeType,
    SectionRuntimeState,
    SectionStatus,
)


class ContinuationPolicyTests(unittest.TestCase):

    def setUp(self):
        self.section = SimpleNamespace(
            section_id="S001",
            max_continuations=2,
        )

    def state(self, continuation_count=0, remaining=None):
        return SectionRuntimeState(
            section_id="S001",
            status=SectionStatus.IN_FLIGHT,
            continuation_count=continuation_count,
            remaining_items=list(remaining or []),
        )

    def coverage(self, remaining):
        return CoverageResult(
            covered_items=[],
            remaining_items=list(remaining),
            semantic_complete=False,
            reason="test",
        )

    def test_complete_with_no_remaining_finalizes(self):
        result = ContinuationPolicy.decide(
            self.section,
            self.state(),
            OutcomeType.COMPLETE,
            self.coverage([]),
        )

        self.assertEqual(result.decision, ContinuationDecision.FINALIZE)

    def test_complete_with_remaining_continues(self):
        result = ContinuationPolicy.decide(
            self.section,
            self.state(),
            OutcomeType.COMPLETE,
            self.coverage(["routing"]),
        )

        self.assertEqual(result.decision, ContinuationDecision.CONTINUE)

    def test_complete_splits_after_continuation_budget(self):
        result = ContinuationPolicy.decide(
            self.section,
            self.state(continuation_count=2),
            OutcomeType.COMPLETE,
            self.coverage(["routing", "recovery"]),
        )

        self.assertEqual(result.decision, ContinuationDecision.SPLIT)

    def test_complete_single_remaining_item_degrades_after_budget(self):
        result = ContinuationPolicy.decide(
            self.section,
            self.state(continuation_count=2),
            OutcomeType.COMPLETE,
            self.coverage(["routing"]),
        )

        self.assertEqual(result.decision, ContinuationDecision.DEGRADE)

    def test_truncated_continues_when_budget_available(self):
        result = ContinuationPolicy.decide(
            self.section,
            self.state(continuation_count=0),
            OutcomeType.TRUNCATED,
            self.coverage(["routing"]),
        )

        self.assertEqual(result.decision, ContinuationDecision.CONTINUE)

    def test_semantic_incomplete_continues_when_budget_available(self):
        result = ContinuationPolicy.decide(
            self.section,
            self.state(continuation_count=1),
            OutcomeType.SEMANTICALLY_INCOMPLETE,
            self.coverage(["routing"]),
        )

        self.assertEqual(result.decision, ContinuationDecision.CONTINUE)

    def test_truncated_splits_after_continuation_budget(self):
        result = ContinuationPolicy.decide(
            self.section,
            self.state(continuation_count=2),
            OutcomeType.TRUNCATED,
            self.coverage(["routing", "recovery"]),
        )

        self.assertEqual(result.decision, ContinuationDecision.SPLIT)

    def test_single_remaining_item_degrades_after_budget(self):
        result = ContinuationPolicy.decide(
            self.section,
            self.state(continuation_count=2),
            OutcomeType.SEMANTICALLY_INCOMPLETE,
            self.coverage(["routing"]),
        )

        self.assertEqual(result.decision, ContinuationDecision.DEGRADE)

    def test_no_progress_degrades(self):
        result = ContinuationPolicy.decide(
            self.section,
            self.state(),
            OutcomeType.NO_PROGRESS,
            self.coverage(["routing"]),
        )

        self.assertEqual(result.decision, ContinuationDecision.DEGRADE)

    def test_provider_failure_degrades(self):
        result = ContinuationPolicy.decide(
            self.section,
            self.state(),
            OutcomeType.PROVIDER_FAILURE,
            self.coverage(["routing"]),
        )

        self.assertEqual(result.decision, ContinuationDecision.DEGRADE)

    def test_structural_invalid_degrades(self):
        result = ContinuationPolicy.decide(
            self.section,
            self.state(),
            OutcomeType.STRUCTURALLY_INVALID,
            self.coverage(["routing"]),
        )

        self.assertEqual(result.decision, ContinuationDecision.DEGRADE)

    def test_incomplete_signal_without_remaining_finalizes(self):
        result = ContinuationPolicy.decide(
            self.section,
            self.state(),
            OutcomeType.TRUNCATED,
            self.coverage([]),
        )

        self.assertEqual(result.decision, ContinuationDecision.FINALIZE)

    def test_policy_does_not_use_token_heuristics(self):
        state = self.state(
            continuation_count=0,
            remaining=["routing"],
        )

        result = ContinuationPolicy.decide(
            self.section,
            state,
            OutcomeType.TRUNCATED,
            self.coverage(["routing"]),
        )

        self.assertEqual(result.decision, ContinuationDecision.CONTINUE)

    def test_reason_is_deterministic(self):
        coverage = self.coverage(["routing"])

        a = ContinuationPolicy.decide(
            self.section,
            self.state(),
            OutcomeType.TRUNCATED,
            coverage,
        )
        b = ContinuationPolicy.decide(
            self.section,
            self.state(),
            OutcomeType.TRUNCATED,
            coverage,
        )

        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()

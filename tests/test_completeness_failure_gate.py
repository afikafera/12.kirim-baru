import unittest

from hermes_agent.orchestrator import HermesAgent


class EvaluatorLLM:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def analyze(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.result


class CompletenessFailureGateTests(unittest.TestCase):
    def test_provider_error_is_not_classified_as_missing_plan_content(self):
        agent = object.__new__(HermesAgent)
        agent.llm = EvaluatorLLM(error=RuntimeError("provider unavailable"))
        fulfilled, reason, missing = agent._evaluate_requirement_fulfillment(
            "topic", "need", ["criterion"], {"fact": "value"}, {}
        )
        self.assertFalse(fulfilled)
        self.assertEqual(missing, [])
        self.assertTrue(agent._is_completeness_evaluator_failure(reason))

    def test_null_evaluator_output_does_not_qualify_for_global_recovery(self):
        agent = object.__new__(HermesAgent)
        agent.llm = EvaluatorLLM(result={"content": None})
        fulfilled, reason, _ = agent._evaluate_requirement_fulfillment(
            "topic", "need", ["criterion"], {"fact": "value"}, {}
        )
        self.assertFalse(fulfilled)
        self.assertTrue(agent._is_completeness_evaluator_failure(reason))

    def test_valid_negative_evaluation_remains_actionable(self):
        agent = object.__new__(HermesAgent)
        agent.llm = EvaluatorLLM(result={"content": '{"fulfilled": false, "missing": ["criterion"], "reason": "evidence absent"}'})
        fulfilled, reason, missing = agent._evaluate_requirement_fulfillment(
            "topic", "need", ["criterion"], {"fact": "value"}, {}
        )
        self.assertFalse(fulfilled)
        self.assertEqual(reason, "evidence absent")
        self.assertEqual(missing, ["criterion"])
        self.assertFalse(agent._is_completeness_evaluator_failure(reason))


    def test_fallback_empty_facts_at_max_retries_does_not_expand_plan(self):
        from unittest.mock import Mock

        agent = object.__new__(HermesAgent)
        requirement = {"topic": "goal [general information]", "need": "general information"}
        plan = {"goal": "goal", "planner_fallback": True, "knowledge_required": [requirement]}
        requirement_map = {"req-1": requirement}
        original_plan = list(plan["knowledge_required"])
        original_map = dict(requirement_map)
        agent._resolve_recovery_requirement = Mock(side_effect=AssertionError("must not recover"))

        recovery = agent._resolve_controller_recovery_requirement(
            "no_request_facts", {}, plan,
            missing_items=["goal: general information"], goal="goal",
        )

        self.assertIsNone(recovery)
        agent._resolve_recovery_requirement.assert_not_called()
        self.assertEqual(len(plan["knowledge_required"]), 1)
        self.assertEqual(plan["knowledge_required"], original_plan)
        self.assertEqual(requirement_map, original_map)

    def test_non_fallback_keeps_existing_recovery_behavior(self):
        agent = object.__new__(HermesAgent)
        plan = {"goal": "goal", "planner_fallback": False}
        recovery = agent._resolve_controller_recovery_requirement(
            "no_request_facts", {}, plan,
            missing_items=["goal: general information"], goal="goal",
        )
        self.assertEqual(recovery["topic"], "goal - goal: general information")
        self.assertTrue(recovery["is_recovery"])


if __name__ == "__main__":
    unittest.main()

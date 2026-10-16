import unittest

from hermes_agent.plan_validator import PlannerContractValidator


class PlanValidatorComparisonAuthorityTests(unittest.TestCase):
    @staticmethod
    def plan(plan_goal, producers=2):
        nodes = []
        for index in range(producers):
            nodes.append({
                "id": f"req_{index + 1}",
                "topic": f"BTC source {index + 1}",
                "need": "current BTC price",
                "produces_deliverable": ["btc_price"],
                "priority": "high",
                "depends_on": [],
                "status": "missing",
            })
        return {
            "goal": plan_goal,
            "deliverables": [{
                "id": "btc_price",
                "type": "number",
                "description": "BTC price",
            }],
            "knowledge_required": nodes,
            "constraints": [],
            "success_criteria": ["price answered"],
            "confidence": 0.8,
        }

    def test_a_original_comparison_authorizes_multiple_producers(self):
        original_goal = "Compare BTC price from two sources"
        plan = self.plan("Current BTC price", producers=2)

        validated = PlannerContractValidator.validate(plan, goal=original_goal)

        self.assertFalse(validated.get("planner_fallback", False))
        self.assertEqual(len(validated["knowledge_required"]), 2)

    def test_b_original_non_comparison_does_not_inherit_plan_wording(self):
        original_goal = "Get the current BTC price"
        plan = self.plan("Compare BTC price from two sources", producers=2)

        validated = PlannerContractValidator.validate(plan, goal=original_goal)

        self.assertTrue(validated.get("planner_fallback"))

    def test_c_existing_comparison_plan_still_passes(self):
        original_goal = "Compare BTC price from two sources"
        plan = self.plan(original_goal, producers=2)

        validated = PlannerContractValidator.validate(plan, goal=original_goal)

        self.assertFalse(validated.get("planner_fallback", False))

    def test_d_existing_non_comparison_plan_still_passes(self):
        original_goal = "Get the current BTC price"
        plan = self.plan(original_goal, producers=1)

        validated = PlannerContractValidator.validate(plan, goal=original_goal)

        self.assertFalse(validated.get("planner_fallback", False))
        self.assertEqual(len(validated["knowledge_required"]), 1)


if __name__ == "__main__":
    unittest.main()

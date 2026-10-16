import json
import re
import unittest

from hermes_agent.orchestrator import AranAgent
from hermes_agent.task_planner import TaskPlanner


def make_plan(goal, topic, need, constraints=None):
    return {
        "goal": goal,
        "deliverables": [
            {
                "id": "answer",
                "type": "string",
                "description": "Answer the user's requested question",
            }
        ],
        "knowledge_required": [
            {
                "id": "req_answer",
                "topic": topic,
                "need": need,
                "produces_deliverable": ["answer"],
                "priority": "high",
                "depends_on": [],
                "status": "missing",
            }
        ],
        "constraints": list(constraints or []),
        "success_criteria": ["The requested answer is supported by the available inputs or evidence"],
        "confidence": 0.9,
    }


class ScriptedPlanner:
    def __init__(self, plans):
        self.plans = list(plans)
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "content": json.dumps(self.plans.pop(0)),
            "finish_reason": "stop",
            "model": "offline-scripted",
        }


class CapturingSearchStage:
    def __init__(self):
        self.calls = []

    def generate(self, query, intent, domain, product):
        self.calls.append(
            {"query": query, "intent": intent, "domain": domain, "product": product}
        )
        return {"search_queries": [query]}


class PlannerAssumptionGuardTests(unittest.TestCase):
    def test_missing_parameter_retries_and_search_receives_unknown_requirement(self):
        goal = (
            "For 12 passenger carriages, determine the total wheel count. "
            "The number of wheels per carriage is not provided; research it."
        )
        bad_raw = make_plan(
            goal,
            "wheel count per passenger carriage",
            "Each carriage has 8 wheels; multiply the carriage count by 8.",
            ["Each carriage has 8 wheels"],
        )
        corrected_raw = make_plan(
            goal,
            "wheel count per passenger carriage",
            "Research an authoritative source for the number of wheels per carriage; "
            "the parameter remains unknown until evidence is found.",
        )
        llm = ScriptedPlanner([bad_raw, corrected_raw])

        with self.assertLogs("hermes_agent.task_planner", level="INFO") as captured:
            plan = TaskPlanner(llm).plan(goal)

        self.assertEqual(len(llm.calls), 2)
        self.assertIn("UNKNOWN", llm.calls[0]["user_query"])
        self.assertIn("CORRECTION REQUIRED", llm.calls[1]["user_query"])
        raw_logs = [entry for entry in captured.output if "[PLANNER RAW]" in entry]
        self.assertEqual(len(raw_logs), 2)
        self.assertIn("8 wheels", raw_logs[0])

        requirement = plan["knowledge_required"][0]
        self.assertEqual(requirement["status"], "missing")
        self.assertIn("per passenger carriage", requirement["topic"])
        self.assertRegex(requirement["need"].lower(), r"research|source|evidence|unknown")
        self.assertEqual(
            TaskPlanner._find_unprovided_numeric_claim_fields(plan, goal),
            [],
        )

        search_stage = CapturingSearchStage()
        agent = AranAgent.__new__(AranAgent)
        agent._strategy_cache = {}
        agent.strategy = search_stage
        agent._get_strategy(requirement["topic"], requirement["need"])

        self.assertEqual(len(search_stage.calls), 1)
        self.assertEqual(
            search_stage.calls[0]["query"],
            f"{requirement['topic']} {requirement['need']}",
        )
        self.assertIsNone(re.search(r"(?<![A-Za-z0-9])\d+(?![A-Za-z0-9])", search_stage.calls[0]["query"]))

    def test_complete_input_values_are_preserved(self):
        goal = "There are 12 passenger carriages and each has 4 wheels. Calculate the total."
        raw = make_plan(
            goal,
            "calculation using the supplied carriage and per-carriage counts",
            "Use only the values provided in the goal; no external fact is needed.",
            ["12 carriages", "4 wheels per carriage"],
        )

        plan = TaskPlanner(ScriptedPlanner([raw])).plan(goal)

        self.assertEqual(plan["constraints"], ["12 carriages", "4 wheels per carriage"])
        self.assertEqual(
            TaskPlanner._find_unprovided_numeric_claim_fields(plan, goal),
            [],
        )

    def test_explicit_user_assumption_is_preserved(self):
        goal = "There are 12 passenger carriages. Assume 8 wheels per carriage and calculate the total."
        raw = make_plan(
            goal,
            "calculation using the supplied count and explicit user assumption",
            "Use the user's explicit assumption as an assumption in the calculation.",
            ["User assumption: 8 wheels per carriage"],
        )

        plan = TaskPlanner(ScriptedPlanner([raw])).plan(goal)

        self.assertEqual(plan["constraints"], ["User assumption: 8 wheels per carriage"])
        self.assertEqual(
            TaskPlanner._find_unprovided_numeric_claim_fields(plan, goal),
            [],
        )

    def test_external_fact_remains_a_legitimate_research_requirement(self):
        goal = (
            "For manufacturer model AC-7, research its published rated capacity "
            "and cite the source."
        )
        raw = make_plan(
            goal,
            "manufacturer-published rated capacity for AC-7",
            "Find the manufacturer's stated capacity and return the sourced value.",
        )

        plan = TaskPlanner(ScriptedPlanner([raw])).plan(goal)

        requirement = plan["knowledge_required"][0]
        self.assertIn("AC-7", requirement["topic"])
        self.assertRegex(requirement["need"].lower(), r"find|research|source")
        self.assertEqual(
            TaskPlanner._find_unprovided_numeric_claim_fields(plan, goal),
            [],
        )

    def test_repeated_unprovided_numeric_claim_falls_back_without_inventing_it(self):
        goal = "Research the missing capacity required to answer the question."
        bad_raw = make_plan(
            goal,
            "standard capacity",
            "The capacity is 25 units.",
        )

        plan = TaskPlanner(ScriptedPlanner([bad_raw, bad_raw])).plan(goal)

        self.assertTrue(plan.get("planner_fallback"))
        fallback_topic = plan["knowledge_required"][0]["topic"]
        self.assertIn("Research the missing capacity", fallback_topic)
        self.assertIsNone(re.search(r"(?<![A-Za-z0-9])\d+(?![A-Za-z0-9])", fallback_topic))
        self.assertEqual(
            TaskPlanner._find_unprovided_numeric_claim_fields(plan, goal),
            [],
        )


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from hermes_agent.orchestrator import AranAgent
from hermes_agent.task_planner import TaskPlanner


def make_plan(goal, need, topic='wheel count per carriage', constraints=None):
    return {
        'goal': goal,
        'deliverables': [{'id': 'answer', 'type': 'string', 'description': 'Answer the requested question'}],
        'knowledge_required': [{
            'id': 'req_answer',
            'topic': topic,
            'need': need,
            'produces_deliverable': ['answer'],
            'priority': 'high',
            'depends_on': [],
            'status': 'missing',
        }],
        'constraints': list(constraints or []),
        'success_criteria': ['Answer supported by supplied facts or research evidence'],
        'confidence': 0.9,
    }


class ScriptedPlanner:
    def __init__(self, *plans):
        self.plans = list(plans)
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        plan = self.plans[min(len(self.calls) - 1, len(self.plans) - 1)]
        return {'content': json.dumps(plan), 'finish_reason': 'stop', 'model': 'offline-provenance-test'}


class CapturingSearchStage:
    def __init__(self):
        self.calls = []

    def generate(self, query, intent, domain, product):
        self.calls.append({'query': query, 'intent': intent, 'domain': domain, 'product': product})
        return {'search_queries': [query]}


class PlannerNumericProvenanceTests(unittest.TestCase):
    def test_speed_value_cannot_be_reused_as_wheel_count(self):
        goal = 'The train travels at 80 km/h and has 10 carriages. What is the total wheel count?'
        bad = make_plan(goal, 'The train has 80 wheels per carriage.', constraints=['80 wheels per carriage'])
        corrected = make_plan(goal, 'Research an authoritative source for the number of wheels per carriage; keep it unknown until sourced.')
        llm = ScriptedPlanner(bad, corrected)
        plan = TaskPlanner(llm).plan(goal)
        self.assertEqual(len(llm.calls), 2, 'mismatched candidate was accepted without retry')
        requirement = plan['knowledge_required'][0]
        self.assertNotIn('80 wheels', requirement['need'])
        self.assertRegex(requirement['need'].lower(), r'research|source|evidence|unknown')

        agent = AranAgent.__new__(AranAgent)
        agent._strategy_cache = {}
        agent.strategy = CapturingSearchStage()
        agent._get_strategy(requirement['topic'], requirement['need'])
        query = agent.strategy.calls[0]['query']
        self.assertNotIn('80', query)
        self.assertRegex(query.lower(), r'research|source|evidence|unknown')

    def test_attribute_matched_user_fact_is_accepted(self):
        goal = 'Each carriage has 80 wheels. There are 10 carriages; calculate the total.'
        raw = make_plan(goal, 'Use the supplied fact: each carriage has 80 wheels.')
        llm = ScriptedPlanner(raw)
        plan = TaskPlanner(llm).plan(goal)
        self.assertEqual(len(llm.calls), 1)
        self.assertIn('80 wheels', plan['knowledge_required'][0]['need'])

    def test_explicit_user_assumption_is_preserved_as_assumption(self):
        goal = 'There are 10 carriages. Assume each carriage has 80 wheels and calculate the total.'
        raw = make_plan(goal, 'Use the user assumption that each carriage has 80 wheels.', constraints=['User assumption: 80 wheels per carriage'])
        llm = ScriptedPlanner(raw)
        plan = TaskPlanner(llm).plan(goal)
        self.assertEqual(len(llm.calls), 1)
        self.assertIn('assumption', plan['knowledge_required'][0]['need'].lower())
        self.assertIn('80 wheels', plan['constraints'][0])

    def test_supported_multiplication_derivation_is_accepted(self):
        goal = 'There are 10 carriages, with 8 wheels per carriage. Calculate the total wheel count.'
        raw = make_plan(goal, '10 carriages × 8 wheels per carriage = 80 total wheels.')
        llm = ScriptedPlanner(raw)
        plan = TaskPlanner(llm).plan(goal)
        self.assertEqual(len(llm.calls), 1)
        self.assertIn('10 carriages', plan['knowledge_required'][0]['need'])
        self.assertIn('8 wheels per carriage', plan['knowledge_required'][0]['need'])
        self.assertIn('80 total wheels', plan['knowledge_required'][0]['need'])

    def test_missing_wheel_count_can_be_researched_without_candidate_value(self):
        goal = 'There are 10 carriages. Determine their total wheel count; research the missing wheel count per carriage.'
        raw = make_plan(goal, 'Research an authoritative source for wheels per carriage; value remains unknown until supported by evidence.')
        llm = ScriptedPlanner(raw)
        plan = TaskPlanner(llm).plan(goal)
        self.assertEqual(len(llm.calls), 1)
        self.assertRegex(plan['knowledge_required'][0]['need'].lower(), r'research|source|evidence|unknown')
        self.assertNotRegex(plan['knowledge_required'][0]['need'], r'(?<![A-Za-z0-9])\d+(?![A-Za-z0-9])')

    def test_repeated_value_in_unrelated_fields_does_not_prove_wheel_count(self):
        goal = 'Train speed is 80 km/h, ticket price is 80 credits. How many wheels does each carriage have?'
        bad = make_plan(goal, 'The train has 80 wheels per carriage.')
        llm = ScriptedPlanner(bad, bad)
        plan = TaskPlanner(llm).plan(goal)
        self.assertEqual(len(llm.calls), 2, 'repeated unrelated values were treated as wheel-count provenance')
        self.assertTrue(plan.get('planner_fallback') or '80 wheels' not in plan['knowledge_required'][0]['need'])


if __name__ == '__main__':
    unittest.main()

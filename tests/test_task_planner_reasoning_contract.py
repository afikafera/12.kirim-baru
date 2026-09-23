import unittest

from hermes_agent.task_planner import TaskPlanner


VALID_PLAN = (
    '{'
    '"goal":"simple goal",'
    '"deliverables":[{"id":"answer","type":"string",'
    '"description":"Direct answer"}],'
    '"knowledge_required":[{"id":"req_1","topic":"simple goal",'
    '"need":"general information","produces_deliverable":["answer"],'
    '"priority":"high","depends_on":[],"status":"missing"}],'
    '"constraints":[],"success_criteria":["question answered"],'
    '"confidence":0.8'
    '}'
)


class FakePlannerLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def result(content, finish_reason="stop"):
    return {
        "content": content,
        "finish_reason": finish_reason,
        "model": "test-model",
    }


class TaskPlannerReasoningContractTests(unittest.TestCase):
    def test_a_valid_json_stop_is_accepted(self):
        llm = FakePlannerLLM([result(VALID_PLAN)])

        plan = TaskPlanner(llm).plan("simple goal")

        self.assertEqual(plan["goal"], "simple goal")
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(llm.calls[0]["max_tokens"], 2048)

    def test_b_think_then_valid_json_stop_is_accepted(self):
        llm = FakePlannerLLM([
            result("<think>internal reasoning</think>\n" + VALID_PLAN),
        ])

        plan = TaskPlanner(llm).plan("simple goal")

        self.assertEqual(plan["goal"], "simple goal")
        self.assertEqual(len(llm.calls), 1)

    def test_c_truncated_json_with_length_is_rejected_and_retried(self):
        llm = FakePlannerLLM([
            result('<think>reasoning</think> {"goal":"simple', "length"),
            result(VALID_PLAN, "stop"),
        ])

        plan = TaskPlanner(llm).plan("simple goal")

        self.assertEqual(plan["goal"], "simple goal")
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(
            [call["max_tokens"] for call in llm.calls],
            [2048, 2048],
        )

    def test_d_finish_reason_length_is_rejected(self):
        llm = FakePlannerLLM([
            result(VALID_PLAN[:40], "length"),
            result(VALID_PLAN[:50], "length"),
        ])

        plan = TaskPlanner(llm).plan("simple goal")

        self.assertTrue(plan.get("planner_fallback"))
        self.assertEqual(len(llm.calls), 2)

    def test_e_no_attempt_sends_more_than_2048_tokens(self):
        llm = FakePlannerLLM([
            RuntimeError("provider rejected max_tokens"),
            RuntimeError("provider rejected max_tokens"),
        ])

        TaskPlanner(llm).plan("simple goal")

        self.assertEqual([call["max_tokens"] for call in llm.calls], [2048, 2048])
        self.assertTrue(all(call["max_tokens"] <= 2048 for call in llm.calls))


if __name__ == "__main__":
    unittest.main()

import json

from hermes_agent.task_planner import TaskPlanner


class FakeLLM:
    def analyze(self, *args, **kwargs):
        return {
            "content": json.dumps({
                "goal": "coba kamu cari di youtube, tuning di 40Hz",
                "deliverables": ["answer"],
                "knowledge_required": [
                    {
                        "topic": "ported enclosure design 40 Hz tuning",
                        "need": "design information",
                        "priority": "high",
                        "depends_on": [],
                        "status": "missing",
                    },
                    {
                        "topic": "YouTube API rate limits documentation",
                        "need": "general information",
                        "priority": "low",
                        "depends_on": [],
                        "status": "missing",
                    },
                ],
                "constraints": [],
                "success_criteria": ["40Hz retained"],
                "confidence": 0.8,
            })
        }


context = """
USER: spesifikasi ACR 12500 Black
ASSISTANT: ACR 12500 Black adalah speaker 12 inch dengan Thiele-Small parameters:
Fs 55 Hz, Qts 0.76, Vas 63.8 liter, Xmax 5.65 mm, sensitivity 97 dB,
impedansi 8 Ohm, power maksimum 450 W.
"""

planner = TaskPlanner(llm_analyzer=FakeLLM())
plan = planner.plan(
    "coba kamu cari di youtube, tidak usah tuning di 24hz terlalu rendah tuning di 40hz saja",
    context=context,
)

topics = [
    item.get("topic", "")
    for item in plan.get("knowledge_required", [])
]

print("RESULT TOPICS:")
for topic in topics:
    print("-", topic)

assert any("ACR 12500 Black" in topic for topic in topics), \
    "FAIL: ACR anchor was not injected"

assert any(
    "ACR 12500 Black" in topic
    and "ported enclosure design 40 Hz tuning" in topic
    for topic in topics
), "FAIL: design topic was not anchored"

assert "YouTube API rate limits documentation" in topics, \
    "FAIL: unrelated topic was unexpectedly modified"

assert all(
    not topic.startswith("ACR 12500 Black ACR 12500 Black")
    for topic in topics
), "FAIL: double prepend detected"

print("PRODUCTION_PATH_ENTITY_NORMALIZE=PASS")

import asyncio

from agent_reach.browser_research_controller import BrowserResearchController


class FakeLLM:
    def __init__(self):
        self.calls = 0

    def analyze(self, system_prompt, user_query, temperature=0.0):
        self.calls += 1

        if self.calls == 1:
            return {
                "content": '{"action":"open","candidate":0}',
            }

        if self.calls == 2:
            return {
                "content": '{"action":"click","target":"e2"}',
            }

        if self.calls == 3:
            return {
                "content": '{"action":"read"}',
            }

        return {
            "content": '{"action":"stop","reason":"smoke test complete"}',
        }


controller = BrowserResearchController(
    llm_analyzer=FakeLLM(),
    max_steps=4,
)

result = controller.explore(
    topic="example domain",
    need="page content",
    candidates=["https://example.com/"],
    session="hermes-smoke-browser-controller",
)

print("=== CONTROLLER RESULT ===")
print("steps:", result["steps"])
print("history:", result["history"])
print("observations:", len(result["observations"]))

assert result["steps"] == 4
assert result["history"][0]["action"] == "open"
assert result["history"][1]["action"] == "click"
assert result["history"][2]["action"] == "read"
assert result["history"][3]["action"] == "stop"

print("BROWSER CONTROLLER SMOKE TEST PASSED")

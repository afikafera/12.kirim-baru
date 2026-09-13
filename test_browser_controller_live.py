from config import load_config
from llm_analyzer.analyzer import LLMAnalyzer
from agent_reach.browser_research_controller import BrowserResearchController


config = load_config()
llm = LLMAnalyzer(config)

controller = BrowserResearchController(
    llm_analyzer=llm,
    max_steps=4,
)

result = controller.explore(
    topic="Example Domain",
    need="Verify the page title and retrieve the visible page text.",
    candidates=["https://example.com/"],
    session="hermes-live-browser-test",
)

print("=== LIVE CONTROLLER RESULT ===")
print("steps:", result["steps"])

for item in result["history"]:
    print(item)

print("observations:", len(result["observations"]))

assert result["steps"] >= 1
assert result["steps"] <= 4
assert result["history"]

print("LIVE BROWSER CONTROLLER TEST COMPLETED")

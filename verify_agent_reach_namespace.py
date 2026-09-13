"""
VERIFY: which physical `agent_reach` package actually gets loaded at
runtime, under the SAME conditions the real Hermes service runs under
(same cwd, same sys.path injection as api/main.py's
`sys.path.insert(0, "/home/arman/research-assistant")`).

This determines whether the agent_reach naming collision (Hermes-side
adapter folder vs upstream Agent-Reach package) is theoretical or
actually happening at runtime. Read-only -- does not modify anything.

Run from the project root (~/research-assistant), exactly as api/main.py
would see sys.path:
    python3 verify_agent_reach_namespace.py
"""
import subprocess
import sys

print("=" * 90)
print("STEP 1 -- sys.path as seen from this working directory")
print("=" * 90)
for i, p in enumerate(sys.path):
    print(f"  [{i}] {p}")

print()
print("=" * 90)
print("STEP 2 -- import agent_reach: which file/path actually resolves")
print("=" * 90)
try:
    import agent_reach
    print(f"agent_reach.__file__ = {getattr(agent_reach, '__file__', None)!r}")
    print(f"agent_reach.__path__ = {list(getattr(agent_reach, '__path__', []))!r}")
    print(f"agent_reach.__version__ = {getattr(agent_reach, '__version__', 'N/A')!r}")
except Exception as e:
    print(f"[IMPORT FAILED] {type(e).__name__}: {e}")

print()
print("=" * 90)
print("STEP 3 -- specific submodule resolution checks")
print("=" * 90)

for modname in [
    "agent_reach.searcher",           # expected: Hermes-side adapter
    "agent_reach.discovery_exa",      # expected: Hermes-side adapter
    "agent_reach.agent_browser_tool", # expected: Hermes-side adapter
    "agent_reach.core",               # expected: upstream Agent-Reach (AgentReach class)
    "agent_reach.channels.youtube",   # expected: upstream Agent-Reach (YouTubeChannel)
    "agent_reach.doctor",             # expected: upstream Agent-Reach
]:
    try:
        mod = __import__(modname, fromlist=["_"])
        print(f"  OK   {modname:35s} -> {getattr(mod, '__file__', '?')}")
    except Exception as e:
        print(f"  FAIL {modname:35s} -> {type(e).__name__}: {e}")

print()
print("=" * 90)
print("STEP 4 -- is upstream Agent-Reach installed as a pip package too?")
print("=" * 90)
result = subprocess.run(
    [sys.executable, "-m", "pip", "show", "agent-reach"],
    capture_output=True, text=True,
)
print("pip show agent-reach:")
print(result.stdout or "(not installed as a pip package)")
if result.stderr.strip():
    print("stderr:", result.stderr.strip())

result2 = subprocess.run(
    [sys.executable, "-m", "pip", "list"],
    capture_output=True, text=True,
)
matching = [
    line for line in result2.stdout.splitlines()
    if "agent" in line.lower() or "reach" in line.lower()
]
print("\npip list entries matching 'agent'/'reach':")
for line in matching:
    print(f"  {line}")
if not matching:
    print("  (none found)")

print()
print("=" * 90)
print("STEP 5 -- confirm the two candidate directories on disk (sanity)")
print("=" * 90)
result3 = subprocess.run(
    ["find", ".", "-maxdepth", "2", "-type", "d", "-name", "agent_reach"],
    capture_output=True, text=True, cwd=".",
)
print("Directories literally named agent_reach found under current dir (depth<=2):")
print(result3.stdout or "(none)")
result4 = subprocess.run(
    ["find", ".", "-maxdepth", "1", "-type", "d", "-iname", "agent-reach*"],
    capture_output=True, text=True, cwd=".",
)
print("Directories named agent-reach* found at top level:")
print(result4.stdout or "(none)")

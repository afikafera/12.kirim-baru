"""
Read-only diagnostic. Does not modify any file, does not import anything
that has side effects beyond what the running server already imports.

Run from the exact same cwd/venv the uvicorn process uses:
    cd ~/research-assistant
    python3 audit_namespace_collision.py

Purpose: resolve whether the Hermes-side `agent_reach/` package and the
upstream Agent-Reach `agent_reach` package name collide at runtime, and
confirm where `agent_reach.discovery_exa` (referenced by
aran_search/searcher.py:638) actually resolves from on the live server.
"""
import sys
import importlib
import json

report = {}

report["sys.path"] = sys.path
report["cwd"] = __import__("os").getcwd()

# 1. Resolve the top-level `agent_reach` package.
try:
    import agent_reach
    report["agent_reach.__file__"] = getattr(agent_reach, "__file__", None)
    report["agent_reach.__path__"] = list(getattr(agent_reach, "__path__", []))
except Exception as e:
    report["agent_reach_import_error"] = repr(e)

# 2. Resolve the exact submodule aran_search/searcher.py imports.
try:
    mod = importlib.import_module("agent_reach.discovery_exa")
    report["agent_reach.discovery_exa.__file__"] = getattr(mod, "__file__", None)
    report["agent_reach.discovery_exa.has_ExaDiscoveryTool"] = hasattr(mod, "ExaDiscoveryTool")
except Exception as e:
    report["agent_reach.discovery_exa_import_error"] = repr(e)

# 3. Resolve other known Hermes-side submodules to confirm they come
#    from the same __path__ as #1 (i.e. no split-namespace surprise).
for sub in ["agent_reach.searcher", "agent_reach.browser_tool", "agent_reach.core"]:
    try:
        m = importlib.import_module(sub)
        report[f"{sub}.__file__"] = getattr(m, "__file__", None)
    except Exception as e:
        report[f"{sub}_import_error"] = repr(e)

# 4. Check if the upstream Agent-Reach project is ALSO pip-installed
#    under a name that could shadow/be-shadowed-by the local package.
try:
    import subprocess
    pip_freeze = subprocess.run(
        [sys.executable, "-m", "pip", "list"],
        capture_output=True, text=True, timeout=20,
    ).stdout
    hits = [
        line for line in pip_freeze.splitlines()
        if "agent" in line.lower() and "reach" in line.lower()
    ]
    report["pip_list_agent_reach_hits"] = hits
except Exception as e:
    report["pip_list_error"] = repr(e)

print(json.dumps(report, indent=2, default=str))

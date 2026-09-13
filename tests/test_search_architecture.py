import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_orchestrator_uses_aran_search_not_legacy_agent_reach():
    path = ROOT / "hermes_agent" / "orchestrator.py"
    source = path.read_text(encoding="utf-8")

    assert "from aran_search.searcher import AgentReachSearcher" in source
    assert "from agent_reach" not in source
    assert "import agent_reach" not in source


def test_active_code_has_no_legacy_agent_reach_imports():
    targets = [
        ROOT / "hermes_agent",
        ROOT / "aran_search",
    ]

    legacy = []

    for target in targets:
        for path in target.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if ".bak" in path.name or ".backup" in path.name or ".orig" in path.name:
                continue

            source = path.read_text(encoding="utf-8")

            for lineno, line in enumerate(source.splitlines(), 1):
                stripped = line.strip()
                if (
                    stripped.startswith("from agent_reach")
                    or stripped.startswith("import agent_reach")
                ):
                    legacy.append(f"{path}:{lineno}:{line}")

    assert legacy == [], "\n".join(legacy)


def test_agent_reach_searcher_search_is_not_called_by_active_project_code():
    targets = [
        ROOT / "hermes_agent",
        ROOT / "aran_search",
        ROOT / "api",
    ]

    hits = []

    for target in targets:
        if not target.exists():
            continue

        for path in target.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if ".bak" in path.name or ".backup" in path.name or ".orig" in path.name:
                continue

            source = path.read_text(encoding="utf-8")

            if "self.searcher.search(" in source:
                hits.append(f"{path}: self.searcher.search(")

            if "AgentReachSearcher(" in source:
                tree = ast.parse(source)

                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func = node.func

                        if (
                            isinstance(func, ast.Attribute)
                            and func.attr == "search"
                            and isinstance(func.value, ast.Attribute)
                            and func.value.attr == "searcher"
                        ):
                            hits.append(
                                f"{path}:{node.lineno}: self.searcher.search() call"
                            )

    # AgentReachSearcher itself defines search(); that definition is allowed.
    filtered = [
        item
        for item in hits
        if not (
            item.startswith(str(ROOT / "aran_search" / "searcher.py"))
            and "self.searcher.search(" not in item
        )
    ]

    assert filtered == [], "\n".join(filtered)


def test_search_executor_points_to_search_gateway():
    path = ROOT / "hermes_agent" / "skill_executors.py"
    source = path.read_text(encoding="utf-8")

    assert "from hermes_agent.search_gateway import SearchGateway" in source
    assert "search_gateway.search(" in source
    assert "searcher.search(" not in source


def test_orchestrator_registers_search_gateway_executor():
    path = ROOT / "hermes_agent" / "orchestrator.py"
    source = path.read_text(encoding="utf-8")

    assert 'self.search_gateway = SearchGateway()' in source
    assert '"agent-reach"' in source
    assert "agent_reach_executor(" in source
    assert "self.search_gateway" in source


def test_fetch_remains_separate_from_search():
    path = ROOT / "hermes_agent" / "orchestrator.py"
    source = path.read_text(encoding="utf-8")

    assert '"agent-reach-fetch"' in source
    assert "agent_reach_fetch_executor(" in source
    assert "self.searcher" in source

#!/usr/bin/env python3
"""
Verification Suite: Capability-Aware Scheduler & Registry (Fase 3)

Validates:
  1. CapabilityResolver deterministic resolution across all categories
  2. CapabilityRegistry source of truth & capability queries
  3. CapabilityScheduler deterministic matching & preference (WEB_FETCH preferred, agent-reach fallback)
  4. Real Runtime Orchestrator: Unsupported capabilities (FINANCIAL, CODE_SEARCH) transition to BLOCKED without calling agent-reach
  5. Real Runtime Orchestrator: Compatible capabilities (WEB_SEARCH, WEATHER) route to correct providers
"""
import os
import sys
import json
import tempfile
from unittest.mock import MagicMock

REPO_ROOT = os.path.expanduser("~/research-assistant")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

if "fcntl" not in sys.modules:
    sys.modules["fcntl"] = MagicMock()

from hermes_agent.knowledge_graph import KnowledgeGraph, NodeExecutionState
from hermes_agent.capability import (
    Capability,
    CapabilityRegistry,
    CapabilityResolver,
    CapabilityScheduler,
)
from hermes_agent.orchestrator import HermesAgent


def test_1_resolver_determinism():
    print("\n[TEST 1] CapabilityResolver Determinism")
    cases = [
        ("Mars Rover specs", "dimensions and mass", Capability.WEB_SEARCH),
        ("Cuaca Bandung", "prakiraan suhu hari ini", Capability.WEATHER),
        ("Weather forecast Tokyo", "rain and temperature", Capability.WEATHER),
        ("Documentation", "https://example.com/api/v1", Capability.WEB_FETCH),
        ("Download dataset", "fetch latest release", Capability.WEB_FETCH),
        ("Saham BBCA", "dividen dan harga saham", Capability.FINANCIAL),
        ("Bitcoin crypto", "kurs valuation", Capability.FINANCIAL),
        ("GitHub repo hermes-agent", "pull request commit diff", Capability.CODE_SEARCH),
        ("General question", "what is photosynthesis", Capability.WEB_SEARCH),
    ]
    for topic, need, expected in cases:
        resolved = CapabilityResolver.resolve(topic, need)
        assert resolved == expected, f"Failed for '{topic}'/'{need}': expected {expected}, got {resolved}"
        print(f"  -> '{topic}' + '{need}' => {resolved} (OK)")
    print("  -> TEST 1 PASSED: CapabilityResolver is 100% deterministic.")


def test_2_registry_source_of_truth():
    print("\n[TEST 2] CapabilityRegistry Source of Truth")
    reg = CapabilityRegistry()

    assert reg.get_provider("agent-reach") is not None
    assert reg.get_provider("agent-reach-fetch") is not None
    assert reg.get_provider("weather") is not None

    reach_caps = reg.get_provider("agent-reach")["capabilities"]
    assert Capability.WEB_SEARCH in reach_caps
    assert Capability.WEB_FETCH in reach_caps

    fetch_caps = reg.get_provider("agent-reach-fetch")["capabilities"]
    assert Capability.WEB_FETCH in fetch_caps
    assert Capability.WEB_SEARCH not in fetch_caps

    weather_caps = reg.get_provider("weather")["capabilities"]
    assert Capability.WEATHER in weather_caps

    web_providers = [p["name"] for p in reg.get_providers_for_capability(Capability.WEB_SEARCH)]
    assert "agent-reach" in web_providers
    assert "agent-reach-fetch" not in web_providers

    fetch_providers = [p["name"] for p in reg.get_providers_for_capability(Capability.WEB_FETCH)]
    assert "agent-reach" in fetch_providers
    assert "agent-reach-fetch" in fetch_providers

    weather_providers = [p["name"] for p in reg.get_providers_for_capability(Capability.WEATHER)]
    assert "weather" in weather_providers

    fin_providers = reg.get_providers_for_capability(Capability.FINANCIAL)
    assert len(fin_providers) == 0, f"Expected 0 financial providers, got {fin_providers}"

    code_providers = reg.get_providers_for_capability(Capability.CODE_SEARCH)
    assert len(code_providers) == 0, f"Expected 0 code providers, got {code_providers}"

    print("  -> TEST 2 PASSED: CapabilityRegistry accurately maps providers and capabilities.")


def test_3_scheduler_matching_and_preference():
    print("\n[TEST 3] CapabilityScheduler Matching & Preference Ordering")
    reg = CapabilityRegistry()
    scheduler = CapabilityScheduler(reg)

    # 1. WEB_SEARCH -> agent-reach
    p_search = scheduler.schedule("Mars Rover", "specs")
    assert p_search is not None and p_search["name"] == "agent-reach", f"Expected agent-reach, got {p_search}"
    print("  -> WEB_SEARCH maps to agent-reach (OK)")

    # 2. WEB_FETCH -> agent-reach-fetch (preferred over agent-reach)
    p_fetch = scheduler.schedule("Direct URL", "https://example.com/doc")
    assert p_fetch is not None and p_fetch["name"] == "agent-reach-fetch", f"Expected agent-reach-fetch, got {p_fetch}"
    print("  -> WEB_FETCH prefers agent-reach-fetch (OK)")

    # 3. WEB_FETCH fallback -> agent-reach when agent-reach-fetch unregistered
    reg_without_fetch = CapabilityRegistry()
    reg_without_fetch.unregister_provider("agent-reach-fetch")
    sched_fallback = CapabilityScheduler(reg_without_fetch)
    p_fallback = sched_fallback.schedule("Direct URL", "https://example.com/doc")
    assert p_fallback is not None and p_fallback["name"] == "agent-reach", f"Expected agent-reach fallback, got {p_fallback}"
    print("  -> WEB_FETCH falls back to agent-reach when preferred provider absent (OK)")

    # 4. WEATHER -> weather
    p_weather = scheduler.schedule("Cuaca Bandung", "suhu")
    assert p_weather is not None and p_weather["name"] == "weather", f"Expected weather, got {p_weather}"
    print("  -> WEATHER maps to weather (OK)")

    # 5. FINANCIAL -> None (unsupported)
    p_fin = scheduler.schedule("Saham BBCA", "harga dan dividen")
    assert p_fin is None, f"Expected None for FINANCIAL, got {p_fin}"
    print("  -> FINANCIAL maps to None (unsupported, zero blind fallback) (OK)")

    # 6. CODE_SEARCH -> None (unsupported)
    p_code = scheduler.schedule("GitHub hermes-agent", "commit diff")
    assert p_code is None, f"Expected None for CODE_SEARCH, got {p_code}"
    print("  -> CODE_SEARCH maps to None (unsupported, zero blind fallback) (OK)")

    print("  -> TEST 3 PASSED: CapabilityScheduler deterministic matching verified.")


def test_4_real_orchestrator_blocked_on_unsupported():
    print("\n[TEST 4] Real Runtime Orchestrator: Unsupported Capabilities Blocked Without Calling agent-reach")

    scenarios = [
        {
            "name": "Financial Requirement",
            "topic": "Saham BBCA dan IHSG",
            "need": "Laporan dividen dan market cap saham",
            "expected_cap": Capability.FINANCIAL,
        },
        {
            "name": "Code Search Requirement",
            "topic": "GitHub Repository hermes-agent",
            "need": "Review pull request commit diff",
            "expected_cap": Capability.CODE_SEARCH,
        },
    ]

    for sc in scenarios:
        print(f"  Testing {sc['name']}...")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_graph = os.path.join(tmpdir, "isolated_kg.json")
            with open(tmp_graph, "w", encoding="utf-8") as f:
                json.dump({"nodes": {}, "edges": [], "_edge_index": []}, f)

            orig_graph_file = KnowledgeGraph.GRAPH_FILE
            KnowledgeGraph.GRAPH_FILE = tmp_graph

            try:
                agent = HermesAgent(
                    memory_manager=MagicMock(),
                    calibrator=MagicMock(),
                    llm_analyzer=MagicMock(),
                    outcome_logger=MagicMock(),
                    lessons_engine=MagicMock(),
                )

                topic = sc["topic"]
                need = sc["need"]
                req_id = agent._make_requirement_id(topic, need)

                # Mock route to research mode
                mock_route = MagicMock()
                mock_route.mode = "research"
                agent.router.route = MagicMock(return_value=mock_route)

                # Mock plan with the unsupported requirement
                agent.task_planner.plan = MagicMock(return_value={
                    "goal": f"Goal for {sc['name']}",
                    "planner_fallback": True,
                    "confidence": 0.9,
                    "knowledge_required": [
                        {"topic": topic, "need": need, "depends_on": []}
                    ],
                    "success_criteria": ["Criteria A"],
                    "constraints": [],
                })

                # Spy on skill execution to ensure agent-reach is NEVER called!
                spy_execute_selected = MagicMock()
                agent.skill_bridge.execute_selected = spy_execute_selected

                # Spy on searcher.search
                spy_search = MagicMock()
                agent.searcher.search = spy_search

                # Limit iterations to 1 cycle
                agent.MAX_ITERATIONS = 1

                # Execute research() on HermesAgent
                result = agent.research(f"Goal for {sc['name']}")

                # Verify spy call counts: ZERO calls!
                assert spy_execute_selected.call_count == 0, (
                    f"CRITICAL VIOLATION: execute_selected was called {spy_execute_selected.call_count} times! "
                    f"Blind fallback was NOT eliminated for unsupported {sc['name']}."
                )
                assert spy_search.call_count == 0, (
                    f"CRITICAL VIOLATION: searcher.search was called {spy_search.call_count} times! "
                    f"agent-reach was invoked despite missing capability."
                )

                # Verify actual node status in KnowledgeGraph is BLOCKED
                kg_check = KnowledgeGraph()
                node_data = kg_check.graph["nodes"].get(req_id, {})
                actual_status = node_data.get("status")
                kg_check.close()

                assert actual_status is not None, f"Node {req_id} not found in KG!"
                assert actual_status == NodeExecutionState.BLOCKED, (
                    f"Expected status '{NodeExecutionState.BLOCKED}', got '{actual_status}' for {sc['name']}"
                )
                print(f"    -> Verified {sc['name']}: status=BLOCKED, execute_selected calls=0, searcher calls=0")

            finally:
                KnowledgeGraph.GRAPH_FILE = orig_graph_file

    print("  -> TEST 4 PASSED: Unsupported capabilities safely BLOCKED with zero blind fallback.")


def test_5_real_orchestrator_routes_compatible_capabilities():
    print("\n[TEST 5] Real Runtime Orchestrator: Routes Compatible Capabilities Correctly")

    scenarios = [
        {
            "name": "Web Search Routing",
            "topic": "Mars Exploration Rover",
            "need": "Specs and scientific instruments",
            "expected_skill": "agent-reach",
        },
        {
            "name": "Weather Routing",
            "topic": "Cuaca Bandung Hari Ini",
            "need": "Prakiraan suhu dan kemungkinan hujan",
            "expected_skill": "weather",
        },
    ]

    for sc in scenarios:
        print(f"  Testing {sc['name']}...")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_graph = os.path.join(tmpdir, "isolated_kg.json")
            with open(tmp_graph, "w", encoding="utf-8") as f:
                json.dump({"nodes": {}, "edges": [], "_edge_index": []}, f)

            orig_graph_file = KnowledgeGraph.GRAPH_FILE
            KnowledgeGraph.GRAPH_FILE = tmp_graph

            try:
                agent = HermesAgent(
                    memory_manager=MagicMock(),
                    calibrator=MagicMock(),
                    llm_analyzer=MagicMock(),
                    outcome_logger=MagicMock(),
                    lessons_engine=MagicMock(),
                )

                topic = sc["topic"]
                need = sc["need"]
                req_id = agent._make_requirement_id(topic, need)

                mock_route = MagicMock()
                mock_route.mode = "research"
                agent.router.route = MagicMock(return_value=mock_route)

                agent.task_planner.plan = MagicMock(return_value={
                    "goal": f"Goal for {sc['name']}",
                    "planner_fallback": True,
                    "confidence": 0.9,
                    "knowledge_required": [
                        {"topic": topic, "need": need, "depends_on": []}
                    ],
                    "success_criteria": ["Criteria A"],
                    "constraints": [],
                })

                agent._strategy_cache[f"{topic}|{need}"] = {
                    "search_queries": [f"{topic} query"],
                    "allowed_sources": [],
                    "score_url": lambda u, s: 0.9,
                }
                agent.strategy.score_url = MagicMock(return_value=0.9)

                selected_skills_called = []
                def mock_exec_selected(skill, q, **kwargs):
                    selected_skills_called.append(skill["name"])
                    return [{"url": "https://example.com/ok"}]

                agent.skill_bridge.execute_selected = MagicMock(side_effect=mock_exec_selected)
                agent.skill_bridge.execute_skill = MagicMock(return_value="Valid mock content that has plenty of length to pass the 50 char check " * 10)

                agent.MAX_ITERATIONS = 1
                agent.research(f"Goal for {sc['name']}")

                assert len(selected_skills_called) > 0, (
                    f"Expected execute_selected to be called for {sc['name']}, but call count was 0!"
                )
                assert selected_skills_called[0] == sc["expected_skill"], (
                    f"Expected provider '{sc['expected_skill']}', but got '{selected_skills_called[0]}'"
                )
                print(f"    -> Verified {sc['name']}: routed to '{selected_skills_called[0]}'")

            finally:
                KnowledgeGraph.GRAPH_FILE = orig_graph_file

    print("  -> TEST 5 PASSED: Compatible capabilities correctly routed to scheduled providers.")


if __name__ == "__main__":
    print("=" * 80)
    print(" RUNNING VERIFY CAPABILITY SCHEDULER SUITE (FASE 3)")
    print("=" * 80)
    test_1_resolver_determinism()
    test_2_registry_source_of_truth()
    test_3_scheduler_matching_and_preference()
    test_4_real_orchestrator_blocked_on_unsupported()
    test_5_real_orchestrator_routes_compatible_capabilities()
    print("\n" + "=" * 80)
    print(" ALL 5 CAPABILITY SCHEDULER VERIFICATION TESTS PASSED!")
    print("=" * 80)

#!/usr/bin/env python3
"""
Test Suite: Explicit Failure States & Invariants (Fase 2)
Verifies:
  1. Registry & Legacy Mapping Validation
  2. Gap Invariant (Failure states never count as complete)
  3. Downstream Dependency Safety (Blocked on dependency failure)
  4. Real Runtime Orchestrator Failure Classification & Searching Eviction
"""
import os
import sys
import json
import tempfile
from unittest.mock import MagicMock

REPO_ROOT = os.path.expanduser("~/research-assistant")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from hermes_agent.knowledge_graph import KnowledgeGraph, NodeExecutionState
from hermes_agent.orchestrator import HermesAgent


def test_1_registry_and_legacy_mapping():
    print("\n[TEST 1] Registry & Legacy Mapping Validation")
    assert NodeExecutionState.PLANNED == "planned", "PLANNED must be 'planned'"
    assert NodeExecutionState.PENDING == "planned", "PENDING must map to 'planned'"
    assert NodeExecutionState.READY == "ready", "READY must be 'ready'"
    assert NodeExecutionState.SEARCHING == "searching", "SEARCHING must be 'searching'"
    assert NodeExecutionState.FOUND == "found", "FOUND must be 'found'"
    assert NodeExecutionState.VERIFIED == "verified", "VERIFIED must be 'verified'"
    assert NodeExecutionState.PARTIAL == "partial", "PARTIAL must be 'partial'"
    assert NodeExecutionState.TIMEOUT == "timeout", "TIMEOUT must be 'timeout'"
    assert NodeExecutionState.EMPTY_CONTENT == "empty_content", "EMPTY_CONTENT must be 'empty_content'"
    assert NodeExecutionState.INVALID_OUTPUT == "invalid_output", "INVALID_OUTPUT must be 'invalid_output'"
    assert NodeExecutionState.AUTH_FAILURE == "auth_failure", "AUTH_FAILURE must be 'auth_failure'"
    assert NodeExecutionState.BLOCKED == "blocked", "BLOCKED must be 'blocked'"
    assert NodeExecutionState.FAILED == "failed", "FAILED must be 'failed'"

    assert NodeExecutionState.SUCCESS_STATES == {"found", "verified"}
    expected_failures = {"timeout", "empty_content", "invalid_output", "auth_failure", "blocked", "failed"}
    assert NodeExecutionState.FAILURE_STATES == expected_failures

    assert "pending" not in KnowledgeGraph.VALID_STATUSES, "'pending' must NOT be in VALID_STATUSES"
    for fs in NodeExecutionState.FAILURE_STATES:
        assert fs in KnowledgeGraph.VALID_STATUSES, f"Failure state '{fs}' must be in VALID_STATUSES"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_graph = os.path.join(tmpdir, "kg_test1.json")
        with open(tmp_graph, "w", encoding="utf-8") as f:
            json.dump({"nodes": {}, "edges": [], "_edge_index": []}, f)

        orig_graph_file = KnowledgeGraph.GRAPH_FILE
        KnowledgeGraph.GRAPH_FILE = tmp_graph
        try:
            kg = KnowledgeGraph()
            for state in NodeExecutionState.FAILURE_STATES:
                node_id = f"test_node_{state}"
                kg.add_node(node_id, status=state)
                assert kg.graph["nodes"][node_id]["status"] == state
                kg.update_status(node_id, state)
                assert kg.graph["nodes"][node_id]["status"] == state
            kg.close()
        finally:
            KnowledgeGraph.GRAPH_FILE = orig_graph_file
    
    print("  -> TEST 1 PASSED: All states registered, legacy mapping intact, VALID_STATUSES correct.")


def test_2_gap_invariant():
    print("\n[TEST 2] Gap Invariant (Failure States Never Complete)")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_graph = os.path.join(tmpdir, "kg_test2.json")
        with open(tmp_graph, "w", encoding="utf-8") as f:
            json.dump({"nodes": {}, "edges": [], "_edge_index": []}, f)

        orig_graph_file = KnowledgeGraph.GRAPH_FILE
        KnowledgeGraph.GRAPH_FILE = tmp_graph
        try:
            kg = KnowledgeGraph()
            goal = "goal_test_gaps"
            kg.add_node(goal, node_type="project")

            kg.add_node("req_success", status=NodeExecutionState.FOUND)
            kg.add_relation(goal, "requires", "req_success")

            kg.add_node("req_partial", status=NodeExecutionState.PARTIAL)
            kg.add_relation(goal, "requires", "req_partial")

            for fs in NodeExecutionState.FAILURE_STATES:
                req_id = f"req_{fs}"
                kg.add_node(req_id, status=fs)
                kg.add_relation(goal, "requires", req_id)

            gaps = kg.find_gaps(goal)
            gap_topics = {g["topic"] for g in gaps}

            assert "req_success" not in gap_topics, "'req_success' (found) must NOT be in gaps"
            assert "req_partial" in gap_topics, "'req_partial' must be in gaps"
            for fs in NodeExecutionState.FAILURE_STATES:
                req_id = f"req_{fs}"
                assert req_id in gap_topics, f"Failure state requirement '{req_id}' must remain in gaps"

            assert len(gaps) == 7, f"Expected 7 gaps (1 partial + 6 failures), got {len(gaps)}"
            kg.close()
        finally:
            KnowledgeGraph.GRAPH_FILE = orig_graph_file

    print("  -> TEST 2 PASSED: All failure states remain in gaps. No failure satisfies completion.")


def test_3_downstream_dependency_safety():
    print("\n[TEST 3] Downstream Dependency Safety (Blocked on Dependency Failure)")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_graph = os.path.join(tmpdir, "kg_test3.json")
        with open(tmp_graph, "w", encoding="utf-8") as f:
            json.dump({"nodes": {}, "edges": [], "_edge_index": []}, f)

        orig_graph_file = KnowledgeGraph.GRAPH_FILE
        KnowledgeGraph.GRAPH_FILE = tmp_graph
        try:
            kg = KnowledgeGraph()
            goal = "goal_pipeline"
            kg.add_node(goal, node_type="project")

            kg.add_node("req_upstream", status=NodeExecutionState.PLANNED)
            kg.add_node("req_downstream", status=NodeExecutionState.PLANNED)
            kg.add_relation(goal, "requires", "req_upstream")
            kg.add_relation(goal, "requires", "req_downstream")
            kg.add_relation("req_downstream", "depends_on", "req_upstream")

            for fs in NodeExecutionState.FAILURE_STATES:
                kg.update_status("req_upstream", fs)
                kg.update_status("req_downstream", NodeExecutionState.PLANNED)

                ready = kg.ready_nodes(goal)
                ready_topics = {r["topic"] for r in ready}

                assert "req_downstream" not in ready_topics, (
                    f"req_downstream must NOT be ready when upstream is {fs}"
                )

                blocked = kg.blocked_nodes(goal)
                blocked_topics = {b["topic"] for b in blocked}
                assert "req_downstream" in blocked_topics, (
                    f"req_downstream must be blocked when upstream is {fs}"
                )

            kg.update_status("req_upstream", NodeExecutionState.FOUND)
            ready = kg.ready_nodes(goal)
            ready_topics = {r["topic"] for r in ready}
            assert "req_downstream" in ready_topics, (
                "req_downstream must become ready once upstream is FOUND"
            )
            kg.close()
        finally:
            KnowledgeGraph.GRAPH_FILE = orig_graph_file

    print("  -> TEST 3 PASSED: Downstream dependency safely blocked on any failure state.")


def test_4_real_orchestrator_failure_runtime():
    print("\n[TEST 4] Real Runtime Orchestrator Failure Classification & Searching Eviction")

    scenarios = [
        {
            "name": "Search Empty (No URLs found)",
            "urls": [],
            "fetch_result": None,
            "expected_state": NodeExecutionState.EMPTY_CONTENT,
        },
        {
            "name": "Fetch Timeout Error",
            "urls": ["https://example.com/timeout"],
            "fetch_result": "Error fetch: HTTPSConnectionPool: Read timed out after 10s",
            "expected_state": NodeExecutionState.TIMEOUT,
        },
        {
            "name": "Fetch 403 Forbidden Error",
            "urls": ["https://example.com/protected"],
            "fetch_result": "Error fetch: 403 Client Error: Forbidden for url",
            "expected_state": NodeExecutionState.AUTH_FAILURE,
        },
        {
            "name": "Empty Response Body (<50 chars)",
            "urls": ["https://example.com/empty"],
            "fetch_result": "Short",
            "expected_state": NodeExecutionState.EMPTY_CONTENT,
        },
        {
            "name": "Generic Fetch Error",
            "urls": ["https://example.com/generic_fail"],
            "fetch_result": "Error fetch: Connection refused by target machine",
            "expected_state": NodeExecutionState.FAILED,
        },
    ]

    for sc in scenarios:
        print(f"  Testing Scenario: {sc['name']}...")
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

                topic = f"Topic_{sc['expected_state']}"
                need = "specs"
                req_id = agent._make_requirement_id(topic, need)

                # Mock route to research mode
                mock_route = MagicMock()
                mock_route.mode = "research"
                agent.router.route = MagicMock(return_value=mock_route)

                # Mock plan with deterministic structure
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

                # Pre-populate strategy cache so no LLM is invoked
                agent._strategy_cache[f"{topic}|{need}"] = {
                    "search_queries": [f"{topic} query"],
                    "allowed_sources": [],
                    "score_url": lambda u, s: 0.9,
                }
                agent.strategy.score_url = MagicMock(return_value=0.9)

                # Mock search URLs
                agent.skill_bridge.execute_selected = MagicMock(
                    return_value=[{"url": u} for u in sc["urls"]]
                )

                # Mock fetch execution
                agent.skill_bridge.execute_skill = MagicMock(
                    return_value=sc["fetch_result"]
                )

                # Limit iterations to 1 cycle
                agent.MAX_ITERATIONS = 1

                # Execute actual research() on HermesAgent
                result = agent.research(f"Goal for {sc['name']}")

                # Inspect actual node in KnowledgeGraph loaded from the isolated temporary store
                kg_check = KnowledgeGraph()
                node_data = kg_check.graph["nodes"].get(req_id, {})
                actual_status = node_data.get("status")
                kg_check.close()

                assert actual_status is not None, f"Node {req_id} not found in KG!"
                assert actual_status != "searching", (
                    f"CRITICAL: Node {req_id} was left in 'searching' state!"
                )
                assert actual_status == sc["expected_state"], (
                    f"Expected status {sc['expected_state']}, got {actual_status} in {sc['name']}"
                )

            finally:
                KnowledgeGraph.GRAPH_FILE = orig_graph_file

    print("  -> TEST 4 PASSED: Real orchestrator runtime classified all failures accurately, zero dangling 'searching' states.")


if __name__ == "__main__":
    print("=" * 80)
    print(" RUNNING VERIFY EXPLICIT FAILURE STATES SUITE (FASE 2)")
    print("=" * 80)
    test_1_registry_and_legacy_mapping()
    test_2_gap_invariant()
    test_3_downstream_dependency_safety()
    test_4_real_orchestrator_failure_runtime()
    print("\n" + "=" * 80)
    print(" ALL 4/4 TESTS PASSED (100%)")
    print("=" * 80)

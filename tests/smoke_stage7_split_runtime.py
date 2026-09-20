"""
Stage 7 Output Scaling — In-Section Composite SPLIT Runtime Smoke Test.

Verifies end-to-end:
1. ContinuationPolicy emits SPLIT when continuation budget is exhausted with multiple remaining items.
2. SectionSplitter.partition() creates deterministic child execution units (S001_c1, S001_c2).
3. Child sections execute independently and are NOT added to OutputManifest or SectionScheduler.
4. SectionSplitter.reconcile() accumulates child output, tokens, and covered items.
5. Reconciled text updates the parent runtime state in SectionStore.
6. Stale overwrite guard (if decision.value != 'SPLIT': store.put(store_state)) preserves STORED_FINAL.
7. Downstream dependencies (e.g., S002 depending on S001) are cleanly unblocked.
8. OutputAggregator produces ScalerStatus.DONE with all sections STORED_FINAL.
9. Full HermesAgent.research() executes the SPLIT flow and returns aggregated output.
"""

from hermes_agent.manifest_builder import ManifestBuilder
from hermes_agent.section_scheduler import SectionScheduler
from hermes_agent.section_store import SectionStore
from hermes_agent.section_worker import SectionWorker
from hermes_agent.section_splitter import SectionSplitter
from hermes_agent.coverage_evaluator import CoverageEvaluator, CoverageResult
from hermes_agent.outcome_classifier import OutcomeClassifier
from hermes_agent.continuation_policy import ContinuationPolicy, ContinuationDecision
from hermes_agent.continuation_engine import ContinuationEngine
from hermes_agent.output_aggregator import OutputAggregator
from hermes_agent.output_manifest import SectionStatus, ScalerStatus
from hermes_agent.orchestrator import HermesAgent


class ControlledSplitLLM:
    """
    Mock LLM simulating truncation on parent and complete coverage on children:
    1. Parent call 1: truncated output covering only 'architecture'
    2. Parent call 2 (continuation): truncated output covering only 'architecture'
    3. Child call 1 (S001_c1): completes coverage for 'memory_system'
    4. Child call 2 (S001_c2): completes coverage for 'recovery_routing'
    5. Section 2 call (S002): completes coverage for 'deployment_procedure'
    """

    def __init__(self):
        self.calls = []

    def analyze(self, system_prompt, user_query, **kwargs):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_query": user_query,
            "kwargs": kwargs,
        })

        # Evidence relevance classifier: production expects strict JSON-compatible
        # content with a boolean "relevant" field.
        if "strict evidence relevance classifier" in system_prompt.lower():
            return {
                "content": {
                    "relevant": True,
                    "reason": "The supplied evidence directly covers the requested topic.",
                },
                "model": "mock-llm",
                "requested_model": "mock-llm",
                "finish_reason": "stop",
                "tokens_input": 40,
                "tokens_output": 12,
                "api_cost": 0.001,
            }

        # Child 1: S001_c1 (must_cover: ['memory_system'])
        if "S001_c1" in system_prompt or "memory_system" in system_prompt:
            return {
                "content": "UserMemory manages conversation state and persistent memory context.",
                "model": "mock-llm",
                "requested_model": "mock-llm",
                "finish_reason": "stop",
                "tokens_input": 120,
                "tokens_output": 35,
                "api_cost": 0.001,
            }

        # Child 2: S001_c2 (must_cover: ['recovery_routing'])
        if "S001_c2" in system_prompt or "recovery_routing" in system_prompt:
            return {
                "content": "SemanticRouter and SkillBridge route recovery requirements to fallback executors.",
                "model": "mock-llm",
                "requested_model": "mock-llm",
                "finish_reason": "stop",
                "tokens_input": 130,
                "tokens_output": 40,
                "api_cost": 0.001,
            }

        # Section S002 (must_cover: ['deployment_procedure'])
        if "S002" in system_prompt:
            return {
                "content": "Deploy using docker-compose up -d and start.sh supervisor script.",
                "model": "mock-llm",
                "requested_model": "mock-llm",
                "finish_reason": "stop",
                "tokens_input": 110,
                "tokens_output": 30,
                "api_cost": 0.001,
            }

        # Parent S001: returns partial text, truncated
        return {
            "content": "SkillBridge connects Hermes core components to specialized skill executors.",
            "model": "mock-llm",
            "requested_model": "mock-llm",
            "finish_reason": "length",
            "tokens_input": 100,
            "tokens_output": 25,
            "api_cost": 0.001,
        }


class ControlledSplitCoverageEvaluator:
    """
    Deterministic coverage evaluator for testing the SPLIT state machine.
    """

    def evaluate(self, section, accumulated_text, facts=None):
        must_cover = list(getattr(section, "must_cover", []) or [])
        text = accumulated_text.lower()

        covered = []
        remaining = []

        for item in must_cover:
            key = item.lower().replace(" ", "_")
            if "architecture" in key and "skillbridge" in text:
                covered.append(item)
            elif "memory" in key and "usermemory" in text:
                covered.append(item)
            elif "recovery" in key and ("semanticrouter" in text or "recovery" in text):
                covered.append(item)
            elif "deployment" in key and "docker" in text:
                covered.append(item)
            else:
                remaining.append(item)

        complete = len(remaining) == 0 and len(covered) > 0

        return CoverageResult(
            covered_items=covered,
            remaining_items=remaining,
            semantic_complete=complete,
            reason="controlled_evaluation",
        )


def test_stage7_split_runtime_pipeline():
    """
    Direct test of the Stage 7 execution loop exercising SPLIT and downstream DAG.
    """
    goal = "Jelaskan arsitektur hermes agent dan cara deployment"

    plan = {
        "knowledge_required": [
            {
                "id": "R001",
                "topic": "Core Architecture",
                "need": "Jelaskan komponen utama",
                "produces_deliverable": [
                    "Architecture Overview",
                    "Memory System",
                    "Recovery Routing",
                ],
                "depends_on": [],
            },
            {
                "id": "R002",
                "topic": "Deployment Procedure",
                "need": "Jelaskan langkah deploy",
                "produces_deliverable": ["Deployment Procedure"],
                "depends_on": ["R001"],
            },
        ],
        "deliverables": [
            {"id": "Architecture Overview", "description": "Architecture Overview"},
            {"id": "Memory System", "description": "Memory System"},
            {"id": "Recovery Routing", "description": "Recovery Routing"},
            {"id": "Deployment Procedure", "description": "Deployment Procedure"},
        ],
        "success_criteria": ["Architecture explained", "Deployment explained"],
        "constraints": [],
    }

    builder = ManifestBuilder(default_max_continuations=1)
    manifest = builder.build(plan, goal=goal)

    assert len(manifest.sections) == 2, f"Expected 2 sections, got {len(manifest.sections)}"
    s1, s2 = manifest.sections[0], manifest.sections[1]
    assert s1.section_id == "S001"
    assert s2.section_id == "S002"
    assert s2.depends_on == ["S001"], f"Expected S002 to depend on S001, got {s2.depends_on}"
    assert len(s1.must_cover) == 4  # topic + 3 deliverables

    llm = ControlledSplitLLM()
    worker = SectionWorker(llm)
    evaluator = ControlledSplitCoverageEvaluator()
    classifier = OutcomeClassifier()
    policy = ContinuationPolicy()
    splitter = SectionSplitter()
    aggregator = OutputAggregator()

    scheduler = SectionScheduler(manifest)
    store = SectionStore()

    for section in manifest.sections:
        store.create(section.section_id)

    engine = ContinuationEngine(
        worker=worker,
        store=store,
        outcome_classifier=classifier,
        coverage_evaluator=evaluator,
        continuation_policy=policy,
    )

    scheduler.initialize()

    split_events = []
    section_context = {
        "all_facts": {"arch": {"value": "SkillBridge", "source": "test"}},
        "synthesis_evidence": [],
        "completeness_context": "COMPLETE",
        "memory_context": "",
        "requirement_audit": [],
    }

    while True:
        ready = scheduler.ready_sections()
        if not ready:
            break

        for section in ready:
            scheduler.mark_in_flight(section.section_id)
            store_state = store.get(section.section_id)
            store_state.status = SectionStatus.IN_FLIGHT
            store.put(store_state)

            while True:
                step = engine.step(
                    section,
                    goal=goal,
                    facts=section_context["all_facts"],
                    evidence=section_context["synthesis_evidence"],
                    context=section_context,
                    max_tokens=section.budget_hint,
                )

                decision = step.policy.decision

                if decision.value == "CONTINUE":
                    continue

                store_state = store.get(section.section_id)

                if decision.value == "FINALIZE":
                    scheduler.mark_complete(section.section_id)
                    store_state.status = SectionStatus.STORED_FINAL

                elif decision.value == "DEGRADE":
                    scheduler.mark_degraded(section.section_id)
                    store_state.status = SectionStatus.DEGRADED

                elif decision.value == "FAIL":
                    scheduler.mark_failed(section.section_id)
                    store_state.status = SectionStatus.FAILED

                elif decision.value == "SPLIT":
                    split_events.append(section.section_id)

                    remaining_items = list(
                        step.coverage.remaining_items
                        if step.coverage is not None
                        else store_state.remaining_items
                    )

                    children = splitter.partition(section, remaining_items)
                    assert len(children) >= 2, f"Expected at least 2 children, got {len(children)}"

                    child_results = []
                    for child in children:
                        child_result = worker.execute(
                            child.section,
                            goal=goal,
                            context=section_context,
                            temperature=0.3,
                            max_tokens=child.section.budget_hint,
                        )

                        content = child_result.get("content", "")
                        tokens_output = int(child_result.get("tokens_output", 0) or 0)

                        child_results.append({
                            "child_section_id": child.child_section_id,
                            "content": content,
                            "tokens_output": tokens_output,
                            "status": SectionStatus.STORED_FINAL,
                            "covered_items": list(child.section.must_cover),
                        })

                    reconciled = splitter.reconcile(
                        parent_section_id=section.section_id,
                        child_results=child_results,
                        remaining_items=remaining_items,
                    )

                    parent_state = store.get(section.section_id)
                    existing_text = parent_state.accumulated_text.strip()
                    child_text = reconciled["accumulated_text"].strip()

                    if existing_text and child_text:
                        parent_state.accumulated_text = f"{existing_text}\n\n{child_text}"
                    elif child_text:
                        parent_state.accumulated_text = child_text

                    if child_text:
                        parent_state.chunks.append(child_text)

                    child_tokens = int(reconciled["tokens_output"] or 0)
                    parent_state.budget_used_tokens += child_tokens
                    parent_state.last_tokens_output = child_tokens
                    parent_state.last_outcome = step.outcome

                    cov = evaluator.evaluate(
                        section,
                        parent_state.accumulated_text,
                        facts=section_context["all_facts"],
                    )

                    parent_state.covered_items = list(cov.covered_items)
                    parent_state.remaining_items = list(cov.remaining_items)

                    if cov.semantic_complete is True:
                        scheduler.mark_complete(section.section_id)
                        parent_state.status = SectionStatus.STORED_FINAL
                    else:
                        scheduler.mark_degraded(section.section_id)
                        parent_state.status = SectionStatus.DEGRADED

                    store.put(parent_state)

                else:
                    scheduler.mark_failed(section.section_id)
                    store_state.status = SectionStatus.FAILED

                # STALE OVERWRITE GUARD:
                if decision.value != "SPLIT":
                    store.put(store_state)
                break

    # Assertions on SPLIT execution
    assert "S001" in split_events, f"S001 should have triggered SPLIT, events: {split_events}"

    # Verify parent state in store was NOT overwritten by stale store_state
    s1_state = store.get("S001")
    assert s1_state.status == SectionStatus.STORED_FINAL, (
        f"S001 expected STORED_FINAL, got {s1_state.status}"
    )
    assert "SkillBridge" in s1_state.accumulated_text, "Parent text missing initial chunk"
    assert "UserMemory" in s1_state.accumulated_text, "Parent text missing child 1 chunk"
    assert "SemanticRouter" in s1_state.accumulated_text, "Parent text missing child 2 chunk"
    assert s1_state.budget_used_tokens > 50, f"Token accounting failed: {s1_state.budget_used_tokens}"

    # Verify downstream section S002 completed after S001
    s2_state = store.get("S002")
    assert s2_state.status == SectionStatus.STORED_FINAL, (
        f"S002 expected STORED_FINAL, got {s2_state.status}"
    )
    assert "docker-compose" in s2_state.accumulated_text, "S002 text missing"

    # Aggregator check
    aggregated = aggregator.aggregate(manifest, store)
    assert aggregated.sections_total == 2
    assert aggregated.sections_final == 2
    assert aggregated.sections_degraded == 0
    assert aggregated.sections_failed == 0
    assert aggregated.scaler_status == ScalerStatus.DONE
    assert "SkillBridge" in aggregated.content
    assert "UserMemory" in aggregated.content
    assert "SemanticRouter" in aggregated.content
    assert "docker-compose" in aggregated.content

    print("STAGE 7 SPLIT RUNTIME PIPELINE: PASS")
    print(f"manifest_id      : {manifest.manifest_id}")
    print(f"split_events     : {split_events}")
    print(f"sections_total   : {aggregated.sections_total}")
    print(f"sections_final   : {aggregated.sections_final}")
    print(f"sections_degraded: {aggregated.sections_degraded}")
    print(f"sections_failed  : {aggregated.sections_failed}")
    print(f"tokens_used      : {aggregated.total_tokens_used}")
    print(f"scaler_status    : {aggregated.scaler_status.value}")
    print(f"llm_calls_total  : {len(llm.calls)}")


def test_hermes_agent_research_split_e2e():
    """
    Verifies HermesAgent.research() executes Stage 7 with SPLIT end-to-end.
    Mocks retrieval to supply verified facts (bypassing zero-facts fail-closed).
    """
    class MockMM:
        def get_all(self):
            return {}

    class MockCal:
        pass

    class MockOutcome:
        def log(self, *args, **kwargs):
            pass

    class MockLessons:
        def get_active(self):
            return []

    llm = ControlledSplitLLM()
    agent = HermesAgent(
        memory_manager=MockMM(),
        calibrator=MockCal(),
        llm_analyzer=llm,
        outcome_logger=MockOutcome(),
        lessons_engine=MockLessons(),
    )

    # Use ControlledSplitCoverageEvaluator for deterministic coverage logic
    agent.coverage_evaluator = ControlledSplitCoverageEvaluator()

    # Pre-configure plan with multiple deliverables to trigger split on truncation
    plan = {
        "goal": "Jelaskan arsitektur hermes agent dan cara deployment",
        "knowledge_required": [
            {
                "id": "R001",
                "topic": "Core Architecture",
                "need": "Jelaskan komponen utama",
                "produces_deliverable": [
                    "Architecture Overview",
                    "Memory System",
                    "Recovery Routing",
                ],
                "depends_on": [],
            },
            {
                "id": "R002",
                "topic": "Deployment Procedure",
                "need": "Jelaskan langkah deploy",
                "produces_deliverable": ["Deployment Procedure"],
                "depends_on": ["R001"],
            },
        ],
        "deliverables": [
            {"id": "Architecture Overview", "description": "Architecture Overview"},
            {"id": "Memory System", "description": "Memory System"},
            {"id": "Recovery Routing", "description": "Recovery Routing"},
            {"id": "Deployment Procedure", "description": "Deployment Procedure"},
        ],
        "success_criteria": ["Architecture explained", "Deployment explained"],
        "constraints": [],
    }

    # Mock task planner to return our multi-deliverable plan
    agent.task_planner.plan = lambda goal, context="": plan
    agent.task_planner.generate_deliverables = lambda plan: plan.get("deliverables", [])

    # Set manifest builder max_continuations=1 so truncation triggers SPLIT on 2nd attempt
    agent.manifest_builder = ManifestBuilder(default_max_continuations=1)

    # Mock the search & extraction phase to return verified facts so zero-facts guard passes
    def mock_extract_facts_batch(evidence, *args, **kwargs):
        return (
            {
                "Core Architecture": {
                    "value": "SkillBridge connects Hermes core to executors",
                    "source": "https://example.test/arch",
                },
                "Deployment Procedure": {
                    "value": "Docker compose up -d",
                    "source": "https://example.test/deploy",
                },
            },
            {},
        )

    agent.facts.extract_facts_batch = mock_extract_facts_batch

    # Mock searcher to return evidence URLs
    agent.searcher.search = lambda q, **kw: "[TEST]\n- Result\n  Content\n  https://example.test/arch"
    agent.searcher.fetch_url = lambda u, **kw: (
        "Hermes Agent uses SkillBridge to connect the Hermes core to executor capabilities. "
        "Deployment can be performed with Docker Compose using the project deployment configuration."
    )

    # Execute research
    result = agent.research("Jelaskan arsitektur hermes agent dan cara deployment")

    assert result is not None, "research() returned None"
    assert result["facts_count"] > 0, f"Expected facts_count > 0, got {result['facts_count']}"
    assert "answer" in result, "Missing answer in research result"
    answer = result["answer"]

    # Verify that the final answer includes content from the split child sections
    assert "SkillBridge" in answer, "Missing parent text in answer"
    assert "UserMemory" in answer, "Missing child 1 reconciled text in answer"
    assert "SemanticRouter" in answer, "Missing child 2 reconciled text in answer"
    assert "docker-compose" in answer, "Missing section 2 text in answer"

    # Verify token profiler recorded output scaling
    assert "output_scaling" in result["token_profile"].get("modules", {}), (
        f"Expected output_scaling in token profile modules: {result['token_profile']}"
    )

    print("HERMES AGENT RESEARCH SPLIT E2E: PASS")
    print(f"facts_count  : {result['facts_count']}")
    print(f"iterations   : {result['iterations']}")
    print(f"pipeline     : {result['pipeline']}")
    print(f"duration_ms  : {result['duration_ms']:.2f}")
    print(f"answer_length: {len(answer)} chars")


def main():
    print("=" * 60)
    print("Stage 7 Output Scaling — SPLIT Runtime Verification")
    print("=" * 60)
    test_stage7_split_runtime_pipeline()
    print("-" * 60)
    test_hermes_agent_research_split_e2e()
    print("=" * 60)
    print("ALL STAGE 7 SPLIT RUNTIME VERIFICATIONS: PASS")
    print("=" * 60)


if __name__ == "__main__":
    main()

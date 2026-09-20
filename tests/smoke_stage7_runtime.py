from hermes_agent.manifest_builder import ManifestBuilder
from hermes_agent.section_scheduler import SectionScheduler
from hermes_agent.section_store import SectionStore
from hermes_agent.section_worker import SectionWorker
from hermes_agent.coverage_evaluator import CoverageEvaluator
from hermes_agent.outcome_classifier import OutcomeClassifier
from hermes_agent.continuation_policy import ContinuationPolicy
from hermes_agent.continuation_engine import ContinuationEngine
from hermes_agent.output_aggregator import OutputAggregator


class SmokeLLM:
    def __init__(self):
        self.calls = []

    def analyze(self, system_prompt, user_query, **kwargs):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_query": user_query,
            "kwargs": kwargs,
        })

        return {
            "content": (
                "Core architecture uses SkillBridge. "
                "The research pipeline separates retrieval from synthesis."
            ),
            "model": "smoke-model",
            "requested_model": "smoke-model",
            "finish_reason": "stop",
            "tokens_input": 100,
            "tokens_output": 25,
            "api_cost": 0,
        }


class SmokeCoverageEvaluator:
    """
    Deterministic coverage evaluator for smoke testing the execution pipeline.
    The production CoverageEvaluator is tested separately.
    """

    def evaluate(self, section, accumulated_text, facts=None):
        return type(
            "CoverageResult",
            (),
            {
                "covered_items": list(section.must_cover),
                "remaining_items": [],
                "semantic_complete": True,
                "reason": "smoke coverage complete",
            },
        )()


def main():
    goal = "Jelaskan arsitektur research assistant"

    plan = {
        "knowledge_required": [
            {
                "requirement_id": "R001",
                "topic": "Core Architecture",
                "need": "Jelaskan alur arsitektur",
                "produces_deliverable": ["architecture overview"],
            },
            {
                "requirement_id": "R002",
                "topic": "Research Pipeline",
                "need": "Jelaskan pipeline research",
                "produces_deliverable": ["pipeline overview"],
            },
        ],
        "success_criteria": ["Architecture explained"],
        "constraints": [],
    }

    llm = SmokeLLM()

    manifest = ManifestBuilder().build(plan, goal=goal)

    assert len(manifest.sections) == 2, (
        f"Expected 2 sections, got {len(manifest.sections)}"
    )

    scheduler = SectionScheduler(manifest)
    store = SectionStore()

    for section in manifest.sections:
        store.create(section.section_id)

    worker = SectionWorker(llm)

    engine = ContinuationEngine(
        worker=worker,
        store=store,
        outcome_classifier=OutcomeClassifier(),
        coverage_evaluator=SmokeCoverageEvaluator(),
        continuation_policy=ContinuationPolicy(),
    )

    scheduler.initialize()

    completed = []

    while True:
        ready = scheduler.ready_sections()

        if not ready:
            break

        for section in ready:
            scheduler.mark_in_flight(section.section_id)

            state = store.get(section.section_id)
            state.status = "IN_FLIGHT"
            store.put(state)

            step = engine.step(
                section,
                goal=goal,
                facts={
                    "architecture": {
                        "value": "SkillBridge separates Core from skills",
                        "source": "smoke",
                    }
                },
                evidence=[],
                context={},
                requirement_audit={},
                memory={},
                max_tokens=500,
            )

            assert step.policy.decision.value == "FINALIZE", (
                f"{section.section_id}: unexpected decision "
                f"{step.policy.decision.value}"
            )

            scheduler.mark_complete(section.section_id)

            state = store.get(section.section_id)
            state.status = "STORED_FINAL"
            store.put(state)

            completed.append(section.section_id)

    aggregated = OutputAggregator().aggregate(manifest, store)

    assert completed == ["S001", "S002"], (
        f"Unexpected completion order: {completed}"
    )

    assert aggregated.sections_total == 2
    assert aggregated.sections_final == 2
    assert aggregated.sections_degraded == 0
    assert aggregated.sections_failed == 0
    assert aggregated.content.strip()
    assert aggregated.scaler_status.value == "DONE"

    assert len(llm.calls) == 2, (
        f"Expected exactly 2 worker calls, got {len(llm.calls)}"
    )

    print("STAGE 7 RUNTIME SMOKE: PASS")
    print(f"manifest_id      : {manifest.manifest_id}")
    print(f"sections_total   : {aggregated.sections_total}")
    print(f"sections_final   : {aggregated.sections_final}")
    print(f"sections_degraded: {aggregated.sections_degraded}")
    print(f"sections_failed  : {aggregated.sections_failed}")
    print(f"tokens_used      : {aggregated.total_tokens_used}")
    print(f"scaler_status    : {aggregated.scaler_status.value}")
    print(f"worker_calls     : {len(llm.calls)}")


if __name__ == "__main__":
    main()

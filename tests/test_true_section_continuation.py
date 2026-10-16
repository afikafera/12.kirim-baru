import json
import unittest

from hermes_agent.continuation_engine import ContinuationEngine
from hermes_agent.continuation_policy import (
    ContinuationDecision,
    ContinuationPolicy,
)
from hermes_agent.coverage_evaluator import CoverageResult
from hermes_agent.outcome_classifier import OutcomeClassifier
from hermes_agent.output_aggregator import OutputAggregator
from hermes_agent.output_manifest import (
    OutcomeType,
    OutputManifest,
    OutputSection,
    ScalerStatus,
    SectionRuntimeState,
    SectionStatus,
)
from hermes_agent.section_scheduler import SectionScheduler
from hermes_agent.section_store import SectionStore
from hermes_agent.section_worker import SectionWorker


class ScriptedLLMAnalyzer:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected LLM call")
        return dict(self.responses.pop(0))


class ScriptedCoverageEvaluator:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def evaluate(self, section, accumulated_text, facts=None):
        self.calls.append({
            "section_id": section.section_id,
            "accumulated_text": accumulated_text,
            "facts": facts,
        })
        if not self.results:
            raise AssertionError("unexpected coverage evaluation")
        return self.results.pop(0)


def make_section(max_continuations=2):
    return OutputSection(
        section_id="S001",
        requirement_id="R001",
        title="Power handling",
        intent="Report the supported power ratings.",
        must_cover=[
            "Power handling is 500 W",
            "Continuous output rating is 250 W",
        ],
        expected_shape="short factual section",
        max_continuations=max_continuations,
    )


def make_response(content, finish_reason, model):
    return {
        "content": content,
        "model": model,
        "requested_model": model,
        "finish_reason": finish_reason,
        "tokens_input": 12,
        "tokens_output": 24,
        "api_cost": 0.0,
    }


def run_section(
    responses, coverage_results, *, model, multi_model_router,
    max_continuations=2,
):
    section = make_section(max_continuations=max_continuations)
    manifest = OutputManifest(
        manifest_id="continuation-test",
        version="1.0",
        goal="Report power ratings from the supplied evidence.",
        sections=[section],
    )
    scheduler = SectionScheduler(manifest)
    scheduler.initialize()
    scheduler.mark_in_flight(section.section_id)

    store = SectionStore()
    store.create(section.section_id)
    state = store.get(section.section_id)
    state.status = SectionStatus.IN_FLIGHT
    store.put(state)

    facts = {
        "power_handling": "500 W",
        "continuous_output_rating": "250 W",
    }
    evidence = [{
        "id": "E001",
        "url": "https://example.test/specs",
        "content": "Power handling 500 W; continuous output 250 W.",
        "provenance": {"source": "manufacturer specification"},
    }]

    llm = ScriptedLLMAnalyzer(responses)
    coverage = ScriptedCoverageEvaluator(coverage_results)
    worker = SectionWorker(llm)
    engine = ContinuationEngine(
        worker=worker,
        store=store,
        outcome_classifier=OutcomeClassifier(),
        coverage_evaluator=coverage,
        continuation_policy=ContinuationPolicy(),
        multi_model_router=multi_model_router,
        request_id="test-section-continuation",
    )

    decisions = []
    pre_step_states = []
    while True:
        pre_step_states.append(store.get(section.section_id))
        step = engine.step(
            section,
            goal=manifest.goal,
            facts=facts,
            evidence=evidence,
            context={"completeness_context": "Evidence supports both ratings."},
            model=model,
        )
        decisions.append(step.policy.decision)
        if step.policy.decision == ContinuationDecision.CONTINUE:
            continue
        if step.policy.decision == ContinuationDecision.FINALIZE:
            scheduler.mark_complete(section.section_id)
            state = store.get(section.section_id)
            state.status = SectionStatus.STORED_FINAL
            store.put(state)
        elif step.policy.decision == ContinuationDecision.DEGRADE:
            scheduler.mark_degraded(section.section_id)
            state = store.get(section.section_id)
            state.status = SectionStatus.DEGRADED
            store.put(state)
        else:
            scheduler.mark_failed(section.section_id)
            state = store.get(section.section_id)
            state.status = SectionStatus.FAILED
            store.put(state)
        break

    aggregate = OutputAggregator().aggregate(manifest, store)
    return {
        "llm": llm,
        "coverage": coverage,
        "store": store,
        "scheduler": scheduler,
        "section": section,
        "facts": facts,
        "evidence": evidence,
        "decisions": decisions,
        "pre_step_states": pre_step_states,
        "aggregate": aggregate,
    }


class TrueSectionContinuationTests(unittest.TestCase):
    def continuation_coverage(self):
        return [
            CoverageResult(
                covered_items=["Power handling is 500 W"],
                remaining_items=["Continuous output rating is 250 W"],
                semantic_complete=False,
                reason="first chunk leaves one item",
            ),
            CoverageResult(
                covered_items=[
                    "Power handling is 500 W",
                    "Continuous output rating is 250 W",
                ],
                remaining_items=[],
                semantic_complete=True,
                reason="both items covered",
            ),
        ]

    def test_truncated_section_prompt_continues_same_work_and_aggregates(self):
        result = run_section(
            [
                make_response(
                    "Power handling is 500 W...",
                    "length",
                    "router-member-a",
                ),
                make_response(
                    "Continuous output rating is 250 W.",
                    "stop",
                    "router-member-b",
                ),
            ],
            self.continuation_coverage(),
            model="9routerpc",
            multi_model_router=True,
        )

        calls = result["llm"].calls
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["decisions"], [
            ContinuationDecision.CONTINUE,
            ContinuationDecision.FINALIZE,
        ])
        self.assertEqual(calls[0]["model"], "9routerpc")
        self.assertEqual(calls[1]["model"], "9routerpc")

        second_state = result["pre_step_states"][1]
        self.assertEqual(second_state.section_id, "S001")
        self.assertEqual(second_state.accumulated_text, "Power handling is 500 W...")
        self.assertEqual(second_state.remaining_items, ["Continuous output rating is 250 W"])

        second_prompt = calls[1]["system_prompt"]
        self.assertIn("SECTION ID:\nS001", second_prompt)
        self.assertIn("REQUIREMENT ID:\nR001", second_prompt)
        self.assertIn("SECTION CONTINUATION", second_prompt)
        self.assertIn("PRIOR PARTIAL OUTPUT:\nPower handling is 500 W...", second_prompt)
        self.assertIn("REMAINING COVERAGE:\n- Continuous output rating is 250 W", second_prompt)
        self.assertIn("REQUIRED COVERAGE:\n- Continuous output rating is 250 W", second_prompt)
        self.assertNotIn("REQUIRED COVERAGE:\n- Power handling is 500 W", second_prompt)
        self.assertIn("Continue this SAME section from the prior partial output.", second_prompt)
        self.assertIn("Cover only the unresolved items.", second_prompt)
        self.assertIn("Do not restart the section.", second_prompt)
        self.assertIn(
            "Do not repeat already-written content unless needed for grammatical continuity.",
            second_prompt,
        )

        facts_json = json.dumps(result["facts"], ensure_ascii=False, separators=(",", ":"))
        evidence_json = json.dumps(result["evidence"], ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(calls[0]["system_prompt"].count(facts_json), 1)
        self.assertEqual(calls[1]["system_prompt"].count(facts_json), 1)
        self.assertEqual(calls[0]["system_prompt"].count(evidence_json), 1)
        self.assertEqual(calls[1]["system_prompt"].count(evidence_json), 1)

        state = result["store"].get("S001")
        self.assertEqual(state.section_id, "S001")
        self.assertEqual(state.status, SectionStatus.STORED_FINAL)
        self.assertEqual(state.accumulated_text, "Power handling is 500 W...\n\nContinuous output rating is 250 W.")
        self.assertEqual(result["aggregate"].scaler_status, ScalerStatus.DONE)
        self.assertIn("Power handling is 500 W...", result["aggregate"].content)
        self.assertIn("Continuous output rating is 250 W.", result["aggregate"].content)
        self.assertEqual(result["aggregate"].content.count("Power handling is 500 W..."), 1)

    def test_chunk_assembly_separates_adjacent_continuation_text(self):
        store = SectionStore()
        store.create("S001")
        store.append_chunk("S001", "Power handling is 500 W.")
        store.append_chunk("S001", "Continuous output rating is 250 W.")
        self.assertEqual(
            store.get("S001").accumulated_text,
            "Power handling is 500 W.\n\nContinuous output rating is 250 W.",
        )

    def test_normal_prompt_is_unchanged_when_continuation_is_false(self):
        worker = SectionWorker(ScriptedLLMAnalyzer([]))
        section = make_section()
        base = {
            "all_facts": {"power_handling": "500 W"},
            "synthesis_evidence": [{"id": "E001", "url": "https://example.test/specs"}],
            "completeness_context": "Evidence supports the rating.",
        }
        legacy_normal_prompt = worker.build_system_prompt(section, context=base)
        runtime_normal_prompt = worker.build_system_prompt(
            section,
            context={
                **base,
                "accumulated_text": "",
                "remaining_items": list(section.must_cover),
                "continuation_count": 0,
                "section_id": "S001",
                "continuation": False,
                "is_continuation": False,
            },
        )
        self.assertEqual(runtime_normal_prompt, legacy_normal_prompt)
        self.assertNotIn("SECTION CONTINUATION", runtime_normal_prompt)

    def test_deepseek_uses_same_section_continuation_without_rotation(self):
        result = run_section(
            [
                make_response("Power handling is 500 W...", "length", "deepseek-flash"),
                make_response("Continuous output rating is 250 W.", "stop", "deepseek-flash"),
            ],
            self.continuation_coverage(),
            model="deepseek-chat",
            multi_model_router=False,
        )
        calls = result["llm"].calls
        self.assertEqual(len(calls), 2)
        self.assertEqual([call["model"] for call in calls], ["deepseek-chat", "deepseek-chat"])
        self.assertIn("SECTION CONTINUATION", calls[1]["system_prompt"])
        self.assertEqual(result["store"].get("S001").status, SectionStatus.STORED_FINAL)

    def test_deepseek_stop_uses_one_call(self):
        result = run_section(
            [make_response("Power handling is 500 W. Continuous output rating is 250 W.", "stop", "deepseek-flash")],
            [CoverageResult(
                covered_items=list(make_section().must_cover),
                remaining_items=[],
                semantic_complete=True,
                reason="complete",
            )],
            model="deepseek-chat",
            multi_model_router=False,
        )
        self.assertEqual(len(result["llm"].calls), 1)
        self.assertNotIn("SECTION CONTINUATION", result["llm"].calls[0]["system_prompt"])

    def empty_coverage(self):
        return CoverageResult(
            covered_items=list(make_section().must_cover),
            remaining_items=[],
            semantic_complete=True,
            reason="all targets reported covered",
        )

    def test_truncated_empty_coverage_continues_then_finalizes_cleanly(self):
        first = "Power handling is 500 W and continuous output is 250 W, while the protection circuit"
        second = "is thermally protected."
        result = run_section(
            [
                make_response(first, "length", "gateway-member-a"),
                make_response(second, "stop", "gateway-member-b"),
            ],
            [self.empty_coverage(), self.empty_coverage()],
            model="9routerpc",
            multi_model_router=True,
        )

        self.assertEqual(len(result["llm"].calls), 2)
        self.assertEqual(result["decisions"], [
            ContinuationDecision.CONTINUE,
            ContinuationDecision.FINALIZE,
        ])
        second_prompt = result["llm"].calls[1]["system_prompt"]
        self.assertIn("SECTION ID:\nS001", second_prompt)
        self.assertIn("PRIOR PARTIAL OUTPUT:\n" + first, second_prompt)
        self.assertIn(
            "Finish the interrupted section from the prior partial output.",
            second_prompt,
        )
        self.assertIn(
            "Do not add new scope or repeat completed content.",
            second_prompt,
        )
        self.assertIn(
            "REMAINING COVERAGE:\n- None; the coverage evaluator reports no unresolved items.",
            second_prompt,
        )
        remaining_block = second_prompt.split("REMAINING COVERAGE:\n", 1)[1].split(
            "\n\nINSTRUCTION:", 1
        )[0]
        self.assertNotIn("Power handling is 500 W", remaining_block)
        self.assertNotIn("Continuous output rating is 250 W", remaining_block)
        self.assertIn('"power_handling":"500 W"', second_prompt)
        self.assertIn('"id":"E001"', second_prompt)
        self.assertEqual(result["coverage"].calls[0]["facts"], result["facts"])
        self.assertEqual(result["coverage"].calls[1]["facts"], result["facts"])

        state = result["store"].get("S001")
        self.assertEqual(state.status, SectionStatus.STORED_FINAL)
        self.assertEqual(result["aggregate"].scaler_status, ScalerStatus.DONE)
        self.assertEqual(state.accumulated_text, first + "\n\n" + second)
        self.assertEqual(state.accumulated_text.count("Power handling is 500 W"), 1)
        self.assertTrue(state.accumulated_text.endswith("thermally protected."))

    def test_persistent_truncation_degrades_when_budget_is_exhausted(self):
        first = "Power handling is 500 W and continuous output is 250 W, while the protection circuit"
        result = run_section(
            [
                make_response(first, "length", "gateway-member-a"),
                make_response("remains active while the protection circuit", "length", "gateway-member-b"),
            ],
            [self.empty_coverage(), self.empty_coverage()],
            model="9routerpc",
            multi_model_router=True,
            max_continuations=1,
        )
        self.assertEqual(len(result["llm"].calls), 2)
        self.assertEqual(result["decisions"], [
            ContinuationDecision.CONTINUE,
            ContinuationDecision.DEGRADE,
        ])
        self.assertEqual(result["store"].get("S001").status, SectionStatus.DEGRADED)
        self.assertEqual(result["aggregate"].scaler_status, ScalerStatus.PARTIAL)

    def test_stop_with_empty_coverage_finalizes_normally(self):
        result = run_section(
            [make_response(
                "Power handling is 500 W and continuous output is 250 W.",
                "stop",
                "gateway-member-a",
            )],
            [self.empty_coverage()],
            model="9routerpc",
            multi_model_router=True,
        )
        self.assertEqual(len(result["llm"].calls), 1)
        self.assertEqual(result["decisions"], [ContinuationDecision.FINALIZE])
        self.assertEqual(result["store"].get("S001").status, SectionStatus.STORED_FINAL)
        self.assertEqual(result["aggregate"].scaler_status, ScalerStatus.DONE)

    def test_deepseek_truncation_continues_empty_coverage_without_rotation(self):
        first = "Power handling is 500 W and continuous output is 250 W, while the protection circuit"
        result = run_section(
            [
                make_response(first, "length", "deepseek-flash"),
                make_response("is thermally protected.", "stop", "deepseek-flash"),
            ],
            [self.empty_coverage(), self.empty_coverage()],
            model="deepseek-chat",
            multi_model_router=False,
        )
        self.assertEqual(len(result["llm"].calls), 2)
        self.assertEqual(
            [call["model"] for call in result["llm"].calls],
            ["deepseek-chat", "deepseek-chat"],
        )
        self.assertEqual(result["decisions"], [
            ContinuationDecision.CONTINUE,
            ContinuationDecision.FINALIZE,
        ])
        second_prompt = result["llm"].calls[1]["system_prompt"]
        self.assertIn("Finish the interrupted section from the prior partial output.", second_prompt)
        self.assertEqual(result["store"].get("S001").status, SectionStatus.STORED_FINAL)

    def test_truncated_with_no_remaining_coverage_continues_with_budget(self):
        section = make_section()
        state = SectionRuntimeState(
            section_id="S001",
            accumulated_text="Power handling is 500 W...",
        )
        result = ContinuationPolicy.decide(
            section,
            state,
            OutcomeType.TRUNCATED,
            self.empty_coverage(),
        )
        self.assertEqual(result.decision, ContinuationDecision.CONTINUE)
        self.assertEqual(result.reason, "truncated_continuation_budget_available")


if __name__ == "__main__":
    unittest.main()

import unittest

from hermes_agent.continuation_engine import ContinuationEngine
from hermes_agent.continuation_policy import ContinuationDecision, ContinuationPolicy
from hermes_agent.output_manifest import OutputManifest, OutputSection, OutcomeType, SectionRuntimeState
from hermes_agent.outcome_classifier import OutcomeClassifier
from hermes_agent.section_store import SectionStore
from hermes_agent.section_worker import SectionWorker


class RecordingLLM:
    def __init__(self, failures=None, router_models=None, null_output_for=None):
        self.failures = failures or {}
        self.router_models = router_models or {}
        self.null_output_for = null_output_for or set()
        self.calls = []
        self.counts = {}

    def analyze(self, *, system_prompt, user_query, temperature=0.3, model=None, max_tokens=None):
        section_id = user_query.split("Write section ", 1)[1].split(":", 1)[0]
        self.counts[section_id] = self.counts.get(section_id, 0) + 1
        attempt = self.counts[section_id]
        upstream = self.router_models.get((section_id, attempt), model)
        call = {
            "section_id": section_id,
            "system_prompt": system_prompt,
            "user_query": user_query,
            "model": model,
            "upstream": upstream,
            "attempt": attempt,
        }
        self.calls.append(call)
        error = self.failures.get((section_id, attempt))
        if error:
            raise RuntimeError(error)
        if section_id in self.null_output_for:
            return {"content": None, "model": upstream}
        return {"content": f"Completed {section_id}", "model": upstream, "finish_reason": "stop"}


class Coverage:
    def evaluate(self, section, accumulated_text, facts=None):
        return type("Result", (), {
            "covered_items": list(section.must_cover) if accumulated_text else [],
            "remaining_items": [] if accumulated_text else list(section.must_cover),
            "semantic_complete": bool(accumulated_text),
            "reason": "test",
        })()


class RecordingWorker:
    def __init__(self, llm):
        self.delegate = SectionWorker(llm)
        self.calls = []

    def execute(self, section, **kwargs):
        context = kwargs.get("context", {})
        self.calls.append({
            "section_id": section.section_id,
            "requirement_id": section.requirement_id,
            "section": section,
            "facts": context.get("all_facts"),
            "evidence": context.get("synthesis_evidence"),
            "model": kwargs.get("model"),
        })
        return self.delegate.execute(section, **kwargs)


class ProviderRetryScopeTests(unittest.TestCase):
    def setUp(self):
        self.sections = [
            OutputSection(
                section_id=f"S000{i}", requirement_id=f"R000{i}",
                title=f"Part {i}", intent=f"Answer requirement {i}",
                must_cover=[f"item {i}"],
            ) for i in range(1, 6)
        ]
        self.manifest = OutputManifest(
            manifest_id="M1", version="1", goal="five separate requirements",
            sections=self.sections,
        )
        self.manifest_before = self.manifest.to_dict()
        self.plan = {
            "goal": self.manifest.goal,
            "knowledge_required": [
                {"id": s.requirement_id, "topic": s.title, "need": s.intent}
                for s in self.sections
            ],
        }
        self.plan_before = {
            "goal": self.plan["goal"],
            "knowledge_required": [dict(item) for item in self.plan["knowledge_required"]],
        }

    def make_engine(self, llm, *, multi_model_router=False):
        store = SectionStore()
        for section in self.sections:
            store.put(SectionRuntimeState(
                section_id=section.section_id,
                remaining_items=list(section.must_cover),
            ))
        worker = RecordingWorker(llm)
        engine = ContinuationEngine(
            worker=worker, store=store,
            outcome_classifier=OutcomeClassifier(),
            coverage_evaluator=Coverage(), continuation_policy=ContinuationPolicy(),
            multi_model_router=multi_model_router,
        )
        return engine, store

    def run_section(self, engine, section, model, facts, evidence):
        results = []
        while True:
            result = engine.step(
                section, goal="Compare the five items independently",
                facts=facts, evidence=evidence, model=model,
            )
            results.append(result)
            if result.policy.decision != ContinuationDecision.CONTINUE:
                return results

    def test_deepseek_success_runs_each_manifest_section_once(self):
        llm = RecordingLLM()
        engine, store = self.make_engine(llm)
        for section in self.sections:
            results = self.run_section(engine, section, "deepseek-chat", {"fact": "fixed"}, [{"source": "fixed"}])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].policy.decision, ContinuationDecision.FINALIZE)

        self.assertEqual([call["section_id"] for call in llm.calls], [s.section_id for s in self.sections])
        self.assertEqual([call["model"] for call in llm.calls], ["deepseek-chat"] * 5)
        self.assertTrue(all(store.get(s.section_id).provider_retry_count == 0 for s in self.sections))
        self.assertEqual(self.plan, self.plan_before)
        self.assertEqual(self.manifest.to_dict(), self.manifest_before)

    def test_deepseek_failure_on_s0003_does_not_retry_or_expand_worker_boundary(self):
        llm = RecordingLLM(failures={("S0003", 1): "context_length_exceeded"})
        engine, _ = self.make_engine(llm)
        facts, evidence = {"fact": "fixed"}, [{"source": "fixed"}]
        results = {}
        for section in self.sections:
            results[section.section_id] = self.run_section(engine, section, "deepseek-chat", facts, evidence)

        s3_calls = [call for call in llm.calls if call["section_id"] == "S0003"]
        self.assertEqual(len(s3_calls), 1)
        self.assertEqual(results["S0003"][-1].policy.decision, ContinuationDecision.DEGRADE)
        self.assertEqual([call["model"] for call in llm.calls], ["deepseek-chat"] * 5)
        for call in llm.calls:
            prompt = call["user_query"] + call["system_prompt"]
            self.assertEqual(sum(s.section_id in prompt for s in self.sections), 1)
        self.assertEqual(self.plan, self.plan_before)
        self.assertEqual(self.manifest.to_dict(), self.manifest_before)

    def test_router_retries_s0004_with_same_requirement_and_scope(self):
        llm = RecordingLLM(
            failures={("S0004", 1): "provider A unavailable"},
            router_models={("S0004", 1): "model-A", ("S0004", 2): "model-B"},
        )
        engine, _ = self.make_engine(llm, multi_model_router=True)
        section = self.sections[3]
        facts, evidence = {"locked": ["f1", "f2"]}, [{"id": "e1"}]
        results = self.run_section(engine, section, "9routerpc", facts, evidence)
        calls = [call for call in llm.calls if call["section_id"] == "S0004"]

        self.assertEqual(len(calls), 2)
        self.assertEqual([call["upstream"] for call in calls], ["model-A", "model-B"])
        self.assertEqual([call["model"] for call in calls], ["9routerpc", "9routerpc"])
        self.assertEqual([call["section_id"] for call in calls], ["S0004", "S0004"])
        worker_calls = [call for call in engine.worker.calls if call["section_id"] == "S0004"]
        self.assertEqual([call["section_id"] for call in worker_calls], ["S0004", "S0004"])
        self.assertEqual([call["requirement_id"] for call in worker_calls], ["R0004", "R0004"])
        self.assertIs(worker_calls[0]["section"], worker_calls[1]["section"])
        self.assertEqual([call["facts"] for call in worker_calls], [facts, facts])
        self.assertEqual([call["evidence"] for call in worker_calls], [evidence, evidence])
        self.assertEqual([call["model"] for call in worker_calls], ["9routerpc", "9routerpc"])
        self.assertIs(section, self.sections[3])
        self.assertEqual(section.requirement_id, "R0004")
        self.assertEqual(calls[0]["user_query"], calls[1]["user_query"])
        self.assertEqual(calls[0]["system_prompt"], calls[1]["system_prompt"])
        self.assertEqual(len(results), 2)
        self.assertEqual(self.plan, self.plan_before)
        self.assertEqual(self.manifest.to_dict(), self.manifest_before)

    def test_single_model_provider_failures_and_null_output_never_expand(self):
        errors = [
            "context_length_exceeded", "model unavailable", "model deprecated",
            "provider error",
        ]
        for error in errors:
            with self.subTest(error=error):
                llm = RecordingLLM(failures={("S0004", 1): error})
                engine, store = self.make_engine(llm)
                results = self.run_section(engine, self.sections[3], "deepseek-chat", {}, [])
                self.assertEqual([r.policy.decision for r in results], [ContinuationDecision.DEGRADE])
                self.assertEqual(results[0].outcome, OutcomeType.PROVIDER_FAILURE)
                self.assertEqual([c["section_id"] for c in llm.calls], ["S0004"])
                self.assertEqual([c["model"] for c in llm.calls], ["deepseek-chat"])
                self.assertEqual(store.get("S0004").provider_retry_count, 0)
                self.assertEqual(self.plan, self.plan_before)
                self.assertEqual(self.manifest.to_dict(), self.manifest_before)

        llm = RecordingLLM(null_output_for={"S0004"})
        engine, _ = self.make_engine(llm)
        result = engine.step(self.sections[3], model="deepseek-chat")
        self.assertEqual(result.outcome, OutcomeType.STRUCTURALLY_INVALID)
        self.assertEqual(result.policy.decision, ContinuationDecision.DEGRADE)
        self.assertEqual([c["section_id"] for c in llm.calls], ["S0004"])
        self.assertEqual(self.manifest.to_dict(), self.manifest_before)

    def test_router_retry_budget_exhaustion_degrades_without_dropping_section(self):
        error = "router provider unavailable"
        llm = RecordingLLM(failures={("S0004", 1): error, ("S0004", 2): error})
        engine, store = self.make_engine(llm, multi_model_router=True)
        results = self.run_section(engine, self.sections[3], "9routerpc", {}, [])

        self.assertEqual([r.policy.decision for r in results], [
            ContinuationDecision.CONTINUE, ContinuationDecision.DEGRADE,
        ])
        self.assertEqual(store.get("S0004").provider_retry_count, 1)
        self.assertEqual(store.get("S0004").remaining_items, ["item 4"])
        self.assertIn("S0004", [section.section_id for section in self.manifest.sections])
        self.assertEqual([call["section_id"] for call in llm.calls], ["S0004", "S0004"])
        self.assertEqual(self.plan, self.plan_before)
        self.assertEqual(self.manifest.to_dict(), self.manifest_before)


if __name__ == "__main__":
    unittest.main()

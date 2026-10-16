import json
import unittest
from unittest.mock import Mock, patch

from hermes_agent.fact_checker import ProviderExhausted, WorkerOutputInvalid
from hermes_agent.output_manifest import OutputManifest
from hermes_agent.orchestrator import HermesAgent


URL = "https://source.test/attachment-spec"
GOAL = "Find the current nominal impedance of the Widget X from source-backed documentation."
TOPIC = "Widget X nominal impedance"
NEED = "nominal impedance"
REQ_ID = f"{TOPIC} [{NEED}]"
EVIDENCE = {
    "evidence_id": "attachment-evidence-1",
    "url": URL,
    "content": "Widget X technical specification: nominal impedance is 8 ohm. This value is explicitly stated in the source document.",
    "evidence_type": "official_docs",
    "source_type": "official_docs",
    "provenance": {"publisher": "source.test", "record": "attachment-evidence-1"},
}


class ScriptedLLM:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def is_multi_model_router(self, model=None):
        return True

    def analyze(self, system_prompt, user_query, temperature=0.1, model=None, max_tokens=None):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_query": user_query,
            "max_tokens": max_tokens,
        })
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class InMemoryUserMemory:
    def search(self, query):
        return []


class InMemoryKnowledgeGraph:
    instances = []

    def __init__(self):
        self.graph = {"nodes": {}}
        self.search_increments = 0
        self.learn_calls = []
        self.instances.append(self)

    def add_node(self, node_id, node_type=None, status="planned", **kwargs):
        self.graph["nodes"].setdefault(
            node_id,
            {"type": node_type, "status": status, "facts": [], **kwargs},
        )

    def add_relation(self, *args, **kwargs):
        return None

    def update_status(self, node_id, status, *args, **kwargs):
        node = self.graph["nodes"].setdefault(node_id, {"facts": []})
        node["status"] = getattr(status, "value", status)

    def increment_search(self, node_id):
        self.search_increments += 1

    def learn(self, req_id, facts, plan):
        self.learn_calls.append((req_id, facts))
        node = self.graph["nodes"].setdefault(req_id, {"facts": []})
        node["facts"].extend(facts.values())

    def save(self):
        return None

    def get_stats(self):
        return {
            "nodes": len(self.graph["nodes"]),
            "facts": sum(len(node.get("facts", [])) for node in self.graph["nodes"].values()),
        }


def plan_for_goal(goal):
    return {
        "goal": goal,
        "deliverables": [{
            "id": "nominal_impedance",
            "type": "string",
            "description": "Widget X nominal impedance",
        }],
        "knowledge_required": [{
            "id": "widget_x_impedance",
            "topic": TOPIC,
            "need": NEED,
            "priority": "high",
            "produces_deliverable": ["nominal_impedance"],
            "depends_on": [],
            "status": "missing",
        }],
        "constraints": [],
        "success_criteria": ["Extract Widget X nominal impedance."],
        "confidence": 0.95,
    }


class AttachmentFactExtractionFailureBaselineTests(unittest.TestCase):
    def _run_research(self, outcomes):
        from hermes_agent import orchestrator as orchestrator_module

        InMemoryKnowledgeGraph.instances = []
        llm = ScriptedLLM(outcomes)
        evidence = json.loads(json.dumps(EVIDENCE))
        with (
            patch.object(orchestrator_module, "KnowledgeGraph", InMemoryKnowledgeGraph),
            patch.object(orchestrator_module, "UserMemory", InMemoryUserMemory),
            patch.object(orchestrator_module, "log_event"),
        ):
            agent = HermesAgent(None, None, llm, None, None)
            plan_mock = Mock(side_effect=lambda goal, context="": plan_for_goal(goal))
            agent.task_planner.plan = plan_mock
            agent._validate_evidence_relevance = Mock(
                side_effect=lambda topic, need, items: items
            )
            agent.strategy.generate = Mock(return_value={
                "intent": "general",
                "domain": "general",
                "goal": "collect relevant information",
                "search_queries": [],
            })
            agent.skill_bridge.execute_skill = Mock()
            agent._resolve_controller_recovery_requirement = Mock(return_value=None)
            agent._inject_recovery_requirement = Mock(return_value=None)
            agent.manifest_builder.build = Mock(return_value=OutputManifest(
                manifest_id="harness",
                version="1.0",
                goal=GOAL,
                sections=[],
            ))
            extractor_inputs = []
            original_extract = agent.facts.extract_facts_batch

            def observe_extract(items, checklist):
                extractor_inputs.append({
                    "evidence": [{
                        key: item.get(key)
                        for key in ("evidence_id", "url", "content", "provenance")
                    } for item in items],
                    "requirement_ids": [entry.get("field_id") for entry in checklist],
                })
                return original_extract(items, checklist)

            agent.facts.extract_facts_batch = observe_extract
            try:
                result = agent.research(GOAL, attachments=[evidence], request_id="attachment-failure-harness")
                escaped = None
            except Exception as exc:
                result = None
                escaped = exc
            return {
                "agent": agent,
                "llm": llm,
                "result": result,
                "escaped": escaped,
                "evidence": evidence,
                "extractor_inputs": extractor_inputs,
                "plan_mock": plan_mock,
                "kg": InMemoryKnowledgeGraph.instances[-1],
            }

    def _assert_failure_handled(self, outcomes, failure_class):
        outcome = self._run_research(outcomes)
        self.assertIsNone(outcome["escaped"])
        result = outcome["result"]
        self.assertEqual(result["research_status"], failure_class)
        self.assertEqual(result["facts_count"], 0)
        self.assertEqual(result["provider_failures"][REQ_ID]["failure_class"], failure_class)
        self.assertEqual(result["provider_failures"][REQ_ID]["attempts"], 2)
        self.assertEqual(outcome["plan_mock"].call_count, 1)  # Initial plan only.
        self.assertEqual(outcome["agent"].skill_bridge.execute_skill.call_count, 0)
        self.assertEqual(outcome["agent"]._resolve_controller_recovery_requirement.call_count, 0)
        self.assertEqual(outcome["agent"]._inject_recovery_requirement.call_count, 0)
        self.assertEqual(outcome["kg"].search_increments, 1)  # One requirement execution; no search retry.
        self.assertEqual(set(outcome["kg"].graph["nodes"]), {GOAL, REQ_ID})
        self.assertEqual(outcome["kg"].graph["nodes"][REQ_ID]["status"], "failed")
        self.assertEqual(outcome["evidence"], EVIDENCE)
        self.assertEqual(len(outcome["extractor_inputs"]), 1)
        accepted = outcome["extractor_inputs"][0]
        self.assertEqual(accepted["requirement_ids"], [REQ_ID])
        self.assertEqual(accepted["evidence"], [{
            key: EVIDENCE.get(key)
            for key in ("evidence_id", "url", "content", "provenance")
        }])

    def test_provider_exhausted_is_recorded_without_research_escape(self):
        self._assert_failure_handled([
            RuntimeError("HTTP 400 Model is unavailable"),
            RuntimeError("HTTP 400 Model is unavailable"),
        ], "PROVIDER_EXHAUSTED")

    def test_worker_output_invalid_is_recorded_without_research_escape(self):
        self._assert_failure_handled([
            {"content": "Markdown prose, not JSON.", "finish_reason": "stop"},
            {"content": "Still prose, not JSON.", "finish_reason": "stop"},
        ], "WORKER_OUTPUT_INVALID")

    def test_attachment_success_facts_continue_normally(self):
        valid = {
            "content": json.dumps({
                "nominal_impedance": {
                    "value": "8 ohm",
                    "source": URL,
                    "source_type": "official_docs",
                },
            }),
            "finish_reason": "stop",
            "tokens_input": 1,
            "tokens_output": 1,
        }
        outcome = self._run_research([valid])
        self.assertIsNone(outcome["escaped"])
        self.assertGreater(outcome["result"]["facts_count"], 0)
        self.assertEqual(len(outcome["extractor_inputs"]), 1)
        self.assertEqual(len(outcome["kg"].learn_calls), 1)
        self.assertEqual(outcome["kg"].learn_calls[0][0], REQ_ID)
        self.assertEqual(outcome["result"]["research_status"], "DONE")


if __name__ == "__main__":
    unittest.main()

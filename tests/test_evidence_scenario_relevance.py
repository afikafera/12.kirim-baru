import json
import re
import unittest
from unittest.mock import Mock, patch

from hermes_agent import orchestrator as orchestrator_module
from hermes_agent.output_manifest import OutputManifest
from hermes_agent.orchestrator import AranAgent


TOPIC = "Scenario Alpha train passenger and carriage scenario"
NEED = (
    "For Scenario Alpha, determine the final passenger count and minimum "
    "carriage count for the specified station sequence. It starts with 100 "
    "passengers at Station A; at Station B 20 leave and 15 board; at Station "
    "C the remaining count is halved; at Station D five couples board. Each "
    "carriage has a maximum capacity of 40 people."
)

GOOD = {
    "url": "https://example.test/scenario-alpha/full",
    "source_type": "official_docs",
    "content": (
        "Scenario Alpha starts with 100 passengers at Station A. At Station B, "
        "20 leave and 15 board, so the count after Station B is 95. This source "
        "supports one intermediate count for the same specified scenario."
    ),
}

SAME_CONTEXT_PARTIAL = {
    "url": "https://example.test/scenario-alpha/capacity",
    "source_type": "datasheet",
    "content": (
        "Scenario Alpha uses carriages limited to 40 people each. This source "
        "supports the capacity field for the same station sequence but does not "
        "state the final passenger count or the number of carriages required."
    ),
}

DIFFERENT_SCENARIO_PARTIAL = {
    "url": "https://studyx.example/train-problem-beta",
    "source_type": "article",
    "content": (
        "Scenario Beta describes a train carrying 2,200 passengers in 8 "
        "carriages, averaging 275 passengers per carriage. It is a different "
        "example with different passenger and station facts from Scenario Alpha."
    ),
}


class ContractFollowingScriptedLLM:
    """Offline relevance judge following the contract in the supplied prompt."""

    def __init__(self):
        self.prompts = []

    def analyze(self, *, system_prompt, user_query, temperature):
        self.prompts.append(user_query)
        content = user_query.split("EVIDENCE CONTENT:\n", 1)[1].split("\n\nTASK:", 1)[0]
        requirement = user_query.split("REQUIREMENT NEED:\n", 1)[1].split("\n\nEVIDENCE URL:", 1)[0]
        has_context_contract = bool(
            re.search(r"same.{0,80}(scenario|entity|context)", user_query, re.I)
            and re.search(r"different.{0,100}(scenario|entity|context)", user_query, re.I)
            and re.search(r"reject", user_query, re.I)
        )
        identifies_alpha = "Scenario Alpha" in requirement
        identifies_beta = "Scenario Beta" in content

        # Reproduce the current any-component contract: the StudyX-like result
        # is accepted because it contains the requested carriage-count topic.
        # Once the prompt requires context identity, explicit Scenario Beta
        # conflicts with the active Scenario Alpha and must be rejected.
        if identifies_alpha and identifies_beta and has_context_contract:
            relevant = False
            reason = "different scenario conflicts with requirement context"
        elif identifies_alpha and identifies_beta:
            relevant = "carriage" in content.lower()
            reason = "partial carriage component overlap"
        elif "Widget Q" in user_query:
            relevant = "Widget Q" in content
            reason = "same identified product supports a requested component"
        else:
            relevant = identifies_alpha and "scenario alpha" in content.lower()
            reason = "same scenario supports one requested component"

        return {
            "content": json.dumps({"relevant": relevant, "reason": reason}),
            "model": "offline-contract-script",
            "finish_reason": "stop",
        }


def validate(evidence):
    agent = object.__new__(AranAgent)
    agent._validation_cache = {}
    agent.llm = ContractFollowingScriptedLLM()
    accepted = agent._validate_evidence_relevance(TOPIC, NEED, [evidence])
    return accepted, agent


class TestEvidenceScenarioRelevance(unittest.TestCase):
    def test_same_scenario_source_is_accepted(self):
        accepted, _agent = validate(GOOD)
        self.assertEqual(accepted, [GOOD])

    def test_same_context_partial_source_is_accepted(self):
        accepted, _agent = validate(SAME_CONTEXT_PARTIAL)
        self.assertEqual(accepted, [SAME_CONTEXT_PARTIAL])

    def test_different_scenario_partial_source_is_rejected(self):
        accepted, agent = validate(DIFFERENT_SCENARIO_PARTIAL)
        self.assertEqual(
            accepted,
            [],
            "different-scenario evidence passed because of partial topic overlap",
        )
        self.assertEqual(len(agent.llm.prompts), 1)


class TestEvidenceRelevanceRegressions(unittest.TestCase):
    def test_same_context_partials_from_official_and_datasheet_sources_aggregate(self):
        accepted, _agent = validate_many([GOOD, SAME_CONTEXT_PARTIAL])
        self.assertEqual(accepted, [GOOD, SAME_CONTEXT_PARTIAL])
        self.assertEqual(GOOD["source_type"], "official_docs")
        self.assertEqual(SAME_CONTEXT_PARTIAL["source_type"], "datasheet")

    def test_ordinary_product_entity_evidence_remains_usable(self):
        evidence = {
            "url": "https://example.test/widget-q/specs",
            "source_type": "official_docs",
            "content": (
                "Widget Q product specification: nominal impedance is 8 ohm. "
                "This official document identifies Widget Q and states one "
                "requested electrical specification for that product."
            ),
        }
        agent = object.__new__(AranAgent)
        agent._validation_cache = {}
        agent.llm = ContractFollowingScriptedLLM()
        accepted = agent._validate_evidence_relevance(
            "Widget Q product specifications",
            "nominal impedance and driver diameter",
            [evidence],
        )
        self.assertEqual(accepted, [evidence])


class PipelineKnowledgeGraph:
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

    def increment_search(self, _node_id):
        self.search_increments += 1

    def learn(self, req_id, facts, _plan):
        self.learn_calls.append((req_id, facts))
        node = self.graph["nodes"].setdefault(req_id, {"facts": []})
        node["facts"].extend(facts.values())

    def save(self):
        return None

    def get_stats(self):
        return {
            "nodes": len(self.graph["nodes"]),
            "facts": sum(len(n.get("facts", [])) for n in self.graph["nodes"].values()),
        }


class PipelineUserMemory:
    def search(self, _query):
        return []


class TestEvidenceRelevancePipeline(unittest.TestCase):
    goal = (
        "Research the specified Scenario Alpha train case using "
        "source documents and determine which required facts they support."
    )

    def run_pipeline(self, evidence, via_search=False):
        from hermes_agent.semantic_router import SemanticRouter

        PipelineKnowledgeGraph.instances = []
        llm = ContractFollowingScriptedLLM()
        plan = {
            "goal": self.goal,
            "deliverables": [{
                "id": "scenario_facts",
                "type": "string",
                "description": "Scenario Alpha facts",
            }],
            "knowledge_required": [{
                "id": "scenario_alpha",
                "topic": TOPIC,
                "need": NEED,
                "priority": "high",
                "depends_on": [],
                "status": "missing",
            }],
            "constraints": [],
            "success_criteria": ["Identify facts for Scenario Alpha."],
            "confidence": 0.95,
        }

        with (
            patch.object(orchestrator_module, "KnowledgeGraph", PipelineKnowledgeGraph),
            patch.object(orchestrator_module, "UserMemory", PipelineUserMemory),
            patch.object(orchestrator_module, "log_event", lambda *args, **kwargs: None),
        ):
            agent = AranAgent(None, None, llm, None, None)
            agent.router = SemanticRouter()
            agent.task_planner.plan = Mock(return_value=plan)
            agent.strategy.generate = Mock(return_value={
                "intent": "general",
                "domain": "general",
                "goal": "collect source-backed evidence",
                "search_queries": ["Scenario Alpha train case"],
            })
            agent.capability_scheduler.schedule = Mock(
                return_value="fake-research-skill" if via_search else None
            )
            if via_search:
                agent.capability_scheduler.schedule_capability = Mock(
                    return_value="fake-search-skill"
                )
                agent.skill_bridge.execute_selected = Mock(return_value=[
                    {"url": item["url"]} for item in evidence
                ])
                agent.strategy.score_url = Mock(return_value=1.0)
                agent._fetch_url_parallel = Mock(return_value=evidence)
            agent._evaluate_requirement_fulfillment = Mock(
                return_value=(True, "scripted fulfilled", [])
            )
            agent.manifest_builder.build = Mock(return_value=OutputManifest(
                manifest_id="evidence-relevance-harness",
                version="1.0",
                goal=self.goal,
                sections=[],
            ))

            extractor_inputs = []

            def extract_only_accepted(items, _checklist):
                extractor_inputs.append(list(items))
                facts = []
                for item in items:
                    if item.get("url") == GOOD["url"]:
                        facts.append({
                            "field": "passengers_after_station_b",
                            "value": 95,
                            "source": item["url"],
                            "source_type": item.get("source_type"),
                        })
                    elif item.get("url") == SAME_CONTEXT_PARTIAL["url"]:
                        facts.append({
                            "field": "carriage_capacity",
                            "value": 40,
                            "source": item["url"],
                            "source_type": item.get("source_type"),
                        })
                    elif item.get("url") == DIFFERENT_SCENARIO_PARTIAL["url"]:
                        facts.append({
                            "field": "carriage_count",
                            "value": 8,
                            "source": item["url"],
                            "source_type": item.get("source_type"),
                        })
                return facts, {
                    "tokens_input": 0,
                    "tokens_output": 0,
                    "api_cost": 0,
                }

            agent.facts.extract_facts_batch = Mock(side_effect=extract_only_accepted)
            agent.facts.evaluate = Mock(return_value={
                "coverage_pct": 100.0,
                "filled": 2,
                "empty": 0,
                "weighted_score": 100.0,
                "sufficient": True,
                "combined_score": 100.0,
                "source_types": ["official_docs", "datasheet"],
            })
            agent.ranker.rank = Mock(side_effect=lambda facts, _query: {
                fact["field"]: fact for fact in facts
            })

            result = agent.research(
                self.goal,
                attachments=[] if via_search else evidence,
                request_id="evidence-relevance-isolated",
            )
            return {
                "agent": agent,
                "result": result,
                "extractor_inputs": extractor_inputs,
                "kg": PipelineKnowledgeGraph.instances[-1],
            }

    def test_rejected_scenario_cannot_reach_extraction_or_satisfy_coverage(self):
        outcome = self.run_pipeline([DIFFERENT_SCENARIO_PARTIAL], via_search=True)
        self.assertEqual(outcome["agent"].router.route(self.goal, has_attachments=False).mode, "research")
        self.assertEqual(outcome["extractor_inputs"], [])
        self.assertEqual(outcome["agent"].facts.extract_facts_batch.call_count, 0)
        self.assertEqual(outcome["kg"].learn_calls, [])
        self.assertEqual(outcome["result"]["facts_count"], 0)
        self.assertNotEqual(outcome["result"]["research_status"], "COMPLETE")

    def test_good_same_context_partials_reach_extraction_and_aggregate(self):
        outcome = self.run_pipeline([
            GOOD,
            SAME_CONTEXT_PARTIAL,
            DIFFERENT_SCENARIO_PARTIAL,
        ], via_search=True)
        self.assertGreater(outcome["agent"].skill_bridge.execute_selected.call_count, 0)
        self.assertEqual(outcome["agent"]._fetch_url_parallel.call_count, 1)
        extracted = outcome["extractor_inputs"]
        self.assertEqual(len(extracted), 1)
        self.assertEqual(
            {item["url"] for item in extracted[0]},
            {GOOD["url"], SAME_CONTEXT_PARTIAL["url"]},
        )
        self.assertNotIn(
            DIFFERENT_SCENARIO_PARTIAL["url"],
            {item["url"] for item in extracted[0]},
        )
        self.assertEqual(outcome["result"]["facts_count"], 2)
        self.assertEqual(len(outcome["kg"].learn_calls), 1)
        accepted_facts = outcome["kg"].learn_calls[0][1]
        self.assertEqual(set(accepted_facts), {
            "passengers_after_station_b",
            "carriage_capacity",
        })
        self.assertTrue(all(
            fact.get("source") != DIFFERENT_SCENARIO_PARTIAL["url"]
            for fact in accepted_facts.values()
        ))


def validate_many(evidence):
    agent = object.__new__(AranAgent)
    agent._validation_cache = {}
    agent.llm = ContractFollowingScriptedLLM()
    accepted = agent._validate_evidence_relevance(TOPIC, NEED, evidence)
    return accepted, agent


if __name__ == "__main__":
    unittest.main()

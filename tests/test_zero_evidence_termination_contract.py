import unittest
from types import SimpleNamespace

from hermes_agent.manifest_builder import ManifestBuilder
from hermes_agent.orchestrator import HermesAgent


class _FakeKnowledgeGraph:
    def add_node(self, *args, **kwargs):
        raise AssertionError("duplicate recovery must not reach KG mutation")

    def add_relation(self, *args, **kwargs):
        raise AssertionError("duplicate recovery must not reach KG mutation")


class ZeroEvidenceTerminationContractTests(unittest.TestCase):
    def test_zero_evidence_is_detected_for_matching_requirement(self):
        section = SimpleNamespace(requirement_id="req_a", title="OpenWrt mwan3")
        audit = [{"req_id": "req_a", "topic": "OpenWrt mwan3", "evidence": 0, "facts": 0}]
        self.assertTrue(HermesAgent._section_has_zero_evidence(section, {}, [], audit))

    def test_evidence_or_facts_prevent_zero_evidence_shortcut(self):
        section = SimpleNamespace(requirement_id="req_a", title="OpenWrt mwan3")
        audit = [{"req_id": "req_a", "topic": "OpenWrt mwan3", "evidence": 1, "facts": 0}]
        self.assertFalse(HermesAgent._section_has_zero_evidence(section, {}, [{"content": "doc"}], audit))

    def test_recovery_semantic_duplicate_is_not_injected(self):
        agent = object.__new__(HermesAgent)
        existing = {"topic": "OpenWrt mwan3", "need": "Collect configuration details"}
        candidate = {"topic": " OpenWrt   mwan3 ", "need": "collect   configuration details"}
        requirement_map = {"existing": existing}
        self.assertIsNone(
            agent._inject_recovery_requirement(
                candidate, {"knowledge_required": [existing]}, requirement_map,
                _FakeKnowledgeGraph(), set(), "goal",
            )
        )
        self.assertEqual(len(requirement_map), 1)

    def test_manifest_deduplicates_semantically_identical_target(self):
        plan = {
            "goal": "Test",
            "knowledge_required": [{
                "id": "req_a",
                "topic": " Target ",
                "need": "documentation",
                "produces_deliverable": ["target", "Other"],
            }],
            "deliverables": [
                {"id": "target", "description": "target"},
                {"id": "Other", "description": "Other deliverable"},
            ],
        }
        section = ManifestBuilder().build(plan).sections[0]
        self.assertEqual(section.must_cover, ["Target", "Other deliverable"])


if __name__ == "__main__":
    unittest.main()

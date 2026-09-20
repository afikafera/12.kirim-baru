"""
Unit tests for ManifestBuilder and OutputManifest contracts.
Verifies deterministic transformation of Planner output into OutputManifest.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermes_agent.output_manifest import (
    OutputManifest,
    OutputSection,
    SectionRuntimeState,
    SectionStatus,
    OutcomeType,
    ScalerStatus,
)
from hermes_agent.manifest_builder import ManifestBuilder


class TestManifestBuilder(unittest.TestCase):

    def setUp(self):
        self.builder = ManifestBuilder(default_budget_hint=None, default_max_continuations=2)
        # Fixture based on Call 02 from Langfuse trace
        self.call02_plan = {
            "goal": "Rancang arsitektur final Hermes untuk menangani task output >5000 token, kompatibel round-robin 9router, dengan kualitas coherent, reliability tinggi, efisiensi token, serta menjawab 15 pertanyaan desain dan memberikan 9 komponen deliverable (A-I)",
            "deliverables": [
                {
                    "id": "component_architecture_overview",
                    "type": "object",
                    "description": "Arsitektur komponen utama Hermes yang dapat menangani output >5000 token dengan komponen utama dan alur kerja"
                },
                {
                    "id": "component_multi_provider_output_handling",
                    "type": "object",
                    "description": "Skema penanganan output multi-provider untuk menggabungkan hasil dari beberapa provider menjadi output tunggal >5000 token"
                },
                {
                    "id": "component_round_robin_integration",
                    "type": "object",
                    "description": "Integrasi round-robin 9router dalam arsitektur Hermes dengan mekanisme pemilihan dan rotasi provider"
                },
                {
                    "id": "component_coherence_mechanism",
                    "type": "object",
                    "description": "Mekanisme pemeliharaan coherence antar hasil provider untuk output yang konsisten dan tidak bertentangan"
                },
                {
                    "id": "component_reliability_framework",
                    "type": "object",
                    "description": "Framework reliability tinggi dengan fallback, retry, dan monitoring system"
                },
                {
                    "id": "component_token_efficiency_strategy",
                    "type": "object",
                    "description": "Strategi optimasi efisiensi token termasuk prompt engineering, caching, dan compression"
                },
                {
                    "id": "component_processing_pipeline",
                    "type": "object",
                    "description": "Pipeline pemrosesan multi-provider dengan queue management dan parallel processing"
                },
                {
                    "id": "component_monitoring_fallback",
                    "type": "object",
                    "description": "Sistem monitoring real-time dan fallback mechanism untuk menjamin availability"
                },
                {
                    "id": "component_implementation_documentation",
                    "type": "object",
                    "description": "Dokumentasi implementasi akhir dengan konfigurasi, API specification, dan deployment guide"
                }
            ],
            "knowledge_required": [
                {
                    "id": "req_hermes_architecture_documentation",
                    "topic": "Dokumentasi arsitektur existing Hermes",
                    "need": "Arsitektur komponen, flow, dan keterbatasan saat ini untuk identifikasi gap dan improvement area",
                    "produces_deliverable": ["component_architecture_overview"],
                    "priority": "high",
                    "depends_on": [],
                    "status": "missing"
                },
                {
                    "id": "req_round_robin_9router_specification",
                    "topic": "Spesifikasi teknis round-robin 9router",
                    "need": "Cara kerja, konfigurasi, dan kemampuan round-robin 9router untuk integrasi yang tepat",
                    "produces_deliverable": ["component_round_robin_integration"],
                    "priority": "high",
                    "depends_on": [],
                    "status": "missing"
                },
                {
                    "id": "req_multi_provider_output_aggregation",
                    "topic": "Teknik aggregasi output multi-provider",
                    "need": "Metode penggabungan hasil dari multiple LLM providers untuk mencapai output >5000 token dengan coherence",
                    "produces_deliverable": ["component_multi_provider_output_handling", "component_coherence_mechanism"],
                    "priority": "high",
                    "depends_on": ["req_hermes_architecture_documentation"],
                    "status": "missing"
                },
                {
                    "id": "req_token_efficiency_optimization",
                    "topic": "Strategi optimasi token efficiency",
                    "need": "Best practices untuk mengurangi token usage sambil menjaga kualitas output",
                    "produces_deliverable": ["component_token_efficiency_strategy"],
                    "priority": "medium",
                    "depends_on": ["req_multi_provider_output_aggregation"],
                    "status": "missing"
                },
                {
                    "id": "req_reliability_patterns",
                    "topic": "Reliability patterns untuk multi-provider systems",
                    "need": "Pola dan best practices untuk mencapai reliability tinggi dalam sistem multi-provider",
                    "produces_deliverable": ["component_reliability_framework", "component_monitoring_fallback"],
                    "priority": "medium",
                    "depends_on": ["req_round_robin_9router_specification"],
                    "status": "missing"
                },
                {
                    "id": "req_processing_pipeline_design",
                    "topic": "Pipeline design untuk multi-provider processing",
                    "need": "Arsitektur pipeline dengan queue management, parallel processing, dan load balancing",
                    "produces_deliverable": ["component_processing_pipeline"],
                    "priority": "medium",
                    "depends_on": ["req_reliability_patterns"],
                    "status": "missing"
                },
                {
                    "id": "req_implementation_examples",
                    "topic": "Contoh implementasi arsitektur serupa",
                    "need": "Case study atau contoh implementasi sistem multi-provider dengan output besar",
                    "produces_deliverable": ["component_implementation_documentation"],
                    "priority": "low",
                    "depends_on": ["req_processing_pipeline_design"],
                    "status": "missing"
                }
            ],
            "constraints": [
                "Output harus melebihi 5000 token",
                "Harus kompatibel dengan round-robin 9router",
                "Kualitas hasil harus coherent",
                "Reliability harus tinggi",
                "Efisiensi token harus optimal"
            ],
            "success_criteria": [
                "Arsitektur dapat menghasilkan output >5000 token secara konsisten",
                "Integrasi round-robin 9router berfungsi dengan benar",
                "Hasil output bersifat coherent (tidak bertentangan)",
                "Reliability system >99% uptime",
                "Efisiensi token dioptimalkan (<10% overhead)",
                "9 komponen deliverable berhasil dibuat",
                "15 pertanyaan desain terjawab lengkap"
            ],
            "confidence": 0.85
        }

    def test_complex_call02_style_plan(self):
        """Test a: Verifies complex multi-deliverable plan is fully converted to OutputManifest."""
        manifest = self.builder.build(self.call02_plan)
        self.assertIsInstance(manifest, OutputManifest)
        self.assertEqual(len(manifest.sections), 7)
        self.assertTrue(manifest.manifest_id.startswith("man_"))
        self.assertEqual(manifest.goal, self.call02_plan["goal"])

        # Check section IDs are sequential
        expected_ids = [f"S{i+1:03d}" for i in range(7)]
        self.assertEqual([s.section_id for s in manifest.sections], expected_ids)

        # Check topic -> title and need -> intent
        s1 = manifest.sections[0]
        self.assertEqual(s1.title, "Dokumentasi arsitektur existing Hermes")
        self.assertEqual(s1.intent, "Arsitektur komponen, flow, dan keterbatasan saat ini untuk identifikasi gap dan improvement area")
        self.assertEqual(s1.priority, "high")

    def test_dependency_translation(self):
        """Test b: Verifies requirement depends_on IDs are correctly translated to section_ids."""
        manifest = self.builder.build(self.call02_plan)
        sec_map = {s.section_id: s for s in manifest.sections}

        # S001 and S002 have no dependencies
        self.assertEqual(sec_map["S001"].depends_on, [])
        self.assertEqual(sec_map["S002"].depends_on, [])

        # S003 depends on req_hermes_architecture_documentation -> S001
        self.assertEqual(sec_map["S003"].depends_on, ["S001"])

        # S004 depends on req_multi_provider_output_aggregation -> S003
        self.assertEqual(sec_map["S004"].depends_on, ["S003"])

        # S005 depends on req_round_robin_9router_specification -> S002
        self.assertEqual(sec_map["S005"].depends_on, ["S002"])

        # S006 depends on req_reliability_patterns -> S005
        self.assertEqual(sec_map["S006"].depends_on, ["S005"])

        # S007 depends on req_processing_pipeline_design -> S006
        self.assertEqual(sec_map["S007"].depends_on, ["S006"])

    def test_produces_deliverable_mapping(self):
        """Test c: Verifies deliverable descriptions are injected into section must_cover."""
        manifest = self.builder.build(self.call02_plan)
        sec_map = {s.section_id: s for s in manifest.sections}

        # S001 produces component_architecture_overview
        s1 = sec_map["S001"]
        self.assertIn("Dokumentasi arsitektur existing Hermes", s1.must_cover)
        self.assertIn("Arsitektur komponen utama Hermes yang dapat menangani output >5000 token dengan komponen utama dan alur kerja", s1.must_cover)

        # S003 produces 2 deliverables
        s3 = sec_map["S003"]
        self.assertIn("Teknik aggregasi output multi-provider", s3.must_cover)
        self.assertIn("Skema penanganan output multi-provider untuk menggabungkan hasil dari beberapa provider menjadi output tunggal >5000 token", s3.must_cover)
        self.assertIn("Mekanisme pemeliharaan coherence antar hasil provider untuk output yang konsisten dan tidak bertentangan", s3.must_cover)

    def test_global_acceptance(self):
        """Test d: Verifies success_criteria is mapped to global_acceptance and NOT copied to sections."""
        manifest = self.builder.build(self.call02_plan)
        self.assertEqual(manifest.global_acceptance, self.call02_plan["success_criteria"])
        self.assertEqual(len(manifest.global_acceptance), 7)

        # Ensure no section carries global acceptance directly
        for s in manifest.sections:
            self.assertFalse(hasattr(s, "global_acceptance"))

    def test_constraints_preserved(self):
        """Test e: Verifies constraints are strictly preserved on the manifest."""
        manifest = self.builder.build(self.call02_plan)
        self.assertEqual(manifest.constraints, self.call02_plan["constraints"])
        self.assertEqual(len(manifest.constraints), 5)

    def test_empty_knowledge_required_fallback(self):
        """Test f: Verifies deterministic fallback when knowledge_required is empty."""
        # Case 1: deliverables present but knowledge_required empty
        plan_with_delivs = {
            "goal": "Hitung harga BTC",
            "deliverables": [
                {"id": "btc_price", "description": "Harga Bitcoin terbaru dalam USD"}
            ],
            "knowledge_required": [],
            "constraints": [],
            "success_criteria": ["Harga didapatkan"]
        }
        m1 = self.builder.build(plan_with_delivs)
        self.assertEqual(len(m1.sections), 1)
        self.assertEqual(m1.sections[0].section_id, "S001")
        self.assertEqual(m1.sections[0].title, "Harga Bitcoin terbaru dalam USD")
        self.assertIn("Harga Bitcoin terbaru dalam USD", m1.sections[0].must_cover)

        # Case 2: both knowledge_required and deliverables empty
        plan_empty = {
            "goal": "Jelaskan apa itu LoRa",
            "deliverables": [],
            "knowledge_required": []
        }
        m2 = self.builder.build(plan_empty)
        self.assertEqual(len(m2.sections), 1)
        self.assertEqual(m2.sections[0].section_id, "S001")
        self.assertEqual(m2.sections[0].requirement_id, "req_fallback_answer")
        self.assertEqual(m2.sections[0].title, "Jelaskan apa itu LoRa")

    def test_deterministic_output(self):
        """Test g: Verifies calling build() twice produces identical manifest structures and IDs."""
        m1 = self.builder.build(self.call02_plan)
        m2 = self.builder.build(self.call02_plan)
        self.assertEqual(m1.manifest_id, m2.manifest_id)
        self.assertEqual(m1.to_dict(), m2.to_dict())

    def test_malformed_and_missing_optional_fields(self):
        """Test h: Verifies robustness against malformed/missing optional fields."""
        plan_sparse = {
            "goal": "Test goal",
            "knowledge_required": [
                {
                    "topic": "Naked topic without id or need",
                    "depends_on": None,
                    "produces_deliverable": "some_str_deliv",
                },
                {
                    "id": "req_2",
                    "topic": "Topic 2",
                    "depends_on": ["Naked topic without id or need"],
                }
            ]
        }
        manifest = self.builder.build(plan_sparse)
        self.assertEqual(len(manifest.sections), 2)
        s1 = manifest.sections[0]
        self.assertEqual(s1.section_id, "S001")
        self.assertEqual(s1.title, "Naked topic without id or need")
        self.assertEqual(s1.intent, "documentation")
        self.assertEqual(s1.priority, "medium")
        self.assertEqual(s1.depends_on, [])
        self.assertIn("some_str_deliv", s1.must_cover)

        s2 = manifest.sections[1]
        self.assertEqual(s2.section_id, "S002")
        self.assertEqual(s2.depends_on, ["S001"])

    def test_section_runtime_state_lifecycle(self):
        """Test SectionRuntimeState serialization and deserialization."""
        state = SectionRuntimeState(
            section_id="S001",
            status=SectionStatus.IN_FLIGHT,
            chunks=["Hello world"],
            accumulated_text="Hello world",
            covered_items=["Item 1"],
            remaining_items=["Item 2"],
            attempts_total=1,
            continuation_count=0,
            budget_used_tokens=500,
            last_model="poolside/laguna-s-2.1",
            last_finish_reason="stop",
            last_tokens_output=500,
            last_outcome=OutcomeType.COMPLETE,
        )
        d = state.to_dict()
        self.assertEqual(d["status"], "IN_FLIGHT")
        self.assertEqual(d["last_outcome"], "COMPLETE")

        restored = SectionRuntimeState.from_dict(d)
        self.assertEqual(restored.section_id, "S001")
        self.assertEqual(restored.status, SectionStatus.IN_FLIGHT)
        self.assertEqual(restored.last_outcome, OutcomeType.COMPLETE)


if __name__ == "__main__":
    unittest.main()

import unittest

from hermes_agent.output_manifest import OutputSection
from hermes_agent.section_worker import (
    SectionWorker,
    is_comparison_section,
    is_recommendation_section,
)


class FakeLLM:
    def __init__(self):
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "content": "Section result.",
            "model": "fake-upstream",
            "requested_model": "fake-provider",
            "finish_reason": "stop",
            "tokens_input": 100,
            "tokens_output": 50,
            "api_cost": 0.01,
        }


class FailingLLM:
    def analyze(self, **kwargs):
        raise RuntimeError("provider unavailable")


def make_section():
    return OutputSection(
        section_id="S001",
        requirement_id="R001",
        title="Architecture",
        intent="Explain the architecture.",
        must_cover=[
            "core flow",
            "output aggregation",
        ],
        expected_shape="structured_markdown",
        budget_hint=1024,
        max_continuations=2,
    )


class TestSectionWorker(unittest.TestCase):

    def test_execute_calls_llm_once_with_explicit_budget(self):
        llm = FakeLLM()
        worker = SectionWorker(llm)

        result = worker.execute(
            make_section(),
            goal="Design the system.",
            context={
                "all_facts": {"fact_a": "value"},
                "synthesis_evidence": [{"url": "https://example.test"}],
                "completeness_context": "RESEARCH STATUS: COMPLETE.",
            },
            max_tokens=1024,
        )

        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(result["content"], "Section result.")
        self.assertEqual(llm.calls[0]["max_tokens"], 1024)
        self.assertEqual(llm.calls[0]["temperature"], 0.3)

    def test_model_is_passed_through_without_selection_logic(self):
        llm = FakeLLM()
        worker = SectionWorker(llm)

        worker.execute(
            make_section(),
            model="selected-provider",
        )

        self.assertEqual(
            llm.calls[0]["model"],
            "selected-provider",
        )

    def test_prompt_contains_section_contract(self):
        llm = FakeLLM()
        worker = SectionWorker(llm)

        worker.execute(
            make_section(),
            goal="Design the system.",
            context={
                "all_facts": {"fact_a": "value"},
                "completeness_context": "INCOMPLETE",
            },
        )

        prompt = llm.calls[0]["system_prompt"]

        self.assertIn("S001", prompt)
        self.assertIn("Architecture", prompt)
        self.assertIn("core flow", prompt)
        self.assertIn("output aggregation", prompt)
        self.assertIn("EXTRACTED FACTS", prompt)

    def test_optional_context_is_safe(self):
        llm = FakeLLM()
        worker = SectionWorker(llm)

        result = worker.execute(
            make_section(),
            goal="Test.",
        )

        self.assertEqual(result["content"], "Section result.")
        self.assertEqual(len(llm.calls), 1)

    def test_llm_exception_propagates(self):
        worker = SectionWorker(FailingLLM())

        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            worker.execute(
                make_section(),
                goal="Test.",
            )

    def test_worker_does_not_retry(self):
        class CountingFailureLLM:
            def __init__(self):
                self.calls = 0

            def analyze(self, **kwargs):
                self.calls += 1
                raise RuntimeError("failure")

        llm = CountingFailureLLM()
        worker = SectionWorker(llm)

        with self.assertRaises(RuntimeError):
            worker.execute(make_section())

        self.assertEqual(llm.calls, 1)

    def test_universal_rules_present_in_all_sections(self):
        llm = FakeLLM()
        worker = SectionWorker(llm)

        worker.execute(
            make_section(),
            goal="Standard section execution.",
        )

        prompt = llm.calls[0]["system_prompt"]
        self.assertIn("FACT FIDELITY:", prompt)
        self.assertIn("SOURCE CONTEXT MATCHING:", prompt)
        self.assertIn("SOURCE SCOPE PRESERVATION & ASYMMETRY PROTECTION:", prompt)
        self.assertIn("Do not negate, reverse, or alter factual values", prompt)
        self.assertIn("Missing facts in research indicate an information gap", prompt)
        self.assertNotIn("COMPARISON-FIRST REASONING:", prompt)
        self.assertNotIn("RECOMMENDATION & DECISION CONTRACT:", prompt)

    def test_comparison_section_receives_comparison_contract(self):
        llm = FakeLLM()
        worker = SectionWorker(llm)

        sec = OutputSection(
            section_id="S002",
            requirement_id="R002",
            title="Perbandingan Protokol WireGuard vs OpenVPN",
            intent="Bandingkan throughput, latency, dan keamanan kedua protokol",
            must_cover=["Throughput", "Latency", "Security"],
        )

        self.assertTrue(is_comparison_section(sec))
        self.assertFalse(is_recommendation_section(sec))

        worker.execute(sec, goal="Evaluasi VPN.")

        prompt = llm.calls[0]["system_prompt"]
        self.assertIn("FACT FIDELITY:", prompt)
        self.assertIn("SOURCE CONTEXT MATCHING:", prompt)
        self.assertIn("SOURCE SCOPE PRESERVATION & ASYMMETRY PROTECTION:", prompt)
        self.assertIn("COMPARISON-FIRST REASONING:", prompt)
        self.assertIn("Do not choose a winner or make a final selection upfront", prompt)
        self.assertNotIn("RECOMMENDATION & DECISION CONTRACT:", prompt)

    def test_recommendation_section_receives_recommendation_contract(self):
        llm = FakeLLM()
        worker = SectionWorker(llm)

        sec = OutputSection(
            section_id="S003",
            requirement_id="R003",
            title="Kesimpulan dan Rekomendasi Arsitektur",
            intent="Berikan rekomendasi akhir berdasarkan hasil riset",
            must_cover=["Rekomendasi", "Action plan"],
        )

        self.assertFalse(is_comparison_section(sec))
        self.assertTrue(is_recommendation_section(sec))

        worker.execute(sec, goal="Pilih arsitektur.")

        prompt = llm.calls[0]["system_prompt"]
        self.assertIn("FACT FIDELITY:", prompt)
        self.assertIn("SOURCE CONTEXT MATCHING:", prompt)
        self.assertIn("SOURCE SCOPE PRESERVATION & ASYMMETRY PROTECTION:", prompt)
        self.assertIn("RECOMMENDATION & DECISION CONTRACT:", prompt)
        self.assertIn("Structure recommendations transparently", prompt)
        self.assertNotIn("COMPARISON-FIRST REASONING:", prompt)

    def test_standard_section_does_not_receive_irrelevant_contextual_contracts(self):
        llm = FakeLLM()
        worker = SectionWorker(llm)

        sec = OutputSection(
            section_id="S004",
            requirement_id="R004",
            title="Spesifikasi Endpoint API Polymarket",
            intent="Dokumentasikan parameter query dan schema response",
            must_cover=["Endpoint URL", "Query params", "Response format"],
        )

        self.assertFalse(is_comparison_section(sec))
        self.assertFalse(is_recommendation_section(sec))

        worker.execute(sec, goal="Dokumentasi API.")

        prompt = llm.calls[0]["system_prompt"]
        self.assertIn("FACT FIDELITY:", prompt)
        self.assertIn("SOURCE CONTEXT MATCHING:", prompt)
        self.assertIn("SOURCE SCOPE PRESERVATION & ASYMMETRY PROTECTION:", prompt)
        self.assertNotIn("COMPARISON-FIRST REASONING:", prompt)
        self.assertNotIn("RECOMMENDATION & DECISION CONTRACT:", prompt)


if __name__ == "__main__":
    unittest.main()

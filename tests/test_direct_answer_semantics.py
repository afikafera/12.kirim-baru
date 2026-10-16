"""Isolated direct-answer semantics contract tests; no provider or service calls."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import hermes_agent.orchestrator as orchestrator
from hermes_agent.orchestrator import AranAgent
from hermes_agent.semantic_router import SemanticRouter


TRAIN_QUERY = (
    "Sebuah kereta berangkat dari stasiun A membawa 100 penumpang. "
    "Di stasiun B, 20 orang turun dan 15 orang naik. "
    "Di stasiun C, jumlah penumpang berkurang setengahnya. "
    "Di stasiun D, 5 pasang suami istri naik. "
    "Berapa jumlah penumpang sekarang dan berapa jumlah total roda kereta "
    "jika setiap gerbong diisi maksimal 40 orang?"
)

def has_direct_semantic_contract(system_prompt):
    prompt = " ".join(system_prompt.casefold().split())
    requirements = (
        "deterministic arithmetic" in prompt,
        "derived only from supplied facts" in prompt,
        "without external sources or citations" in prompt,
        "required input is missing" in prompt,
        "cannot be determined from the provided information" in prompt,
        "name the missing input" in prompt,
        "generic defaults" in prompt and "outside facts" in prompt,
        "external knowledge only when" in prompt
        and "explicitly asks for external research" in prompt,
        "discrete entities" in prompt,
        "non-integer count" in prompt,
        "preserve the numeric result" in prompt,
        "domain inconsistency" in prompt,
        "do not silently round or replace" in prompt,
    )
    return all(requirements)


class Trap:
    def __init__(self, counters, name):
        self.counters = counters
        self.name = name

    def __getattr__(self, method):
        def called(*args, **kwargs):
            self.counters[self.name] += 1
            raise AssertionError(f"unexpected {self.name}.{method} call")
        return called


class DirectRouter:
    """Force the already-selected direct branch for isolated answer tests."""
    def route(self, *args, **kwargs):
        return SimpleNamespace(mode="direct", reason="test_direct", confidence=1.0)


class ScriptedLLM:
    """Offline fixture keyed to the direct prompt contract, never a provider."""
    def __init__(self):
        self.calls = []

    def analyze(self, system_prompt, user_query, temperature=0.3):
        self.calls.append((system_prompt, user_query, temperature))
        contract_present = has_direct_semantic_contract(system_prompt)
        query = user_query.casefold()
        if "stasiun a" in query:
            if contract_present:
                content = (
                    "B: 100 - 20 + 15 = 95. C: 95 / 2 = 47.5, sehingga "
                    "jumlah penumpang tidak konsisten untuk orang yang "
                    "berjumlah diskret. Jika diteruskan secara literal, D "
                    "menghasilkan 57.5; kapasitas 40 berarti 2 gerbong. "
                    "Jumlah roda tidak dapat ditentukan karena roda per "
                    "gerbong tidak diberikan."
                )
            else:
                content = (
                    "Jumlahnya 57.5 penumpang. Dengan 8 roda per gerbong, "
                    "2 gerbong memiliki 16 roda."
                )
        elif "gerbong" in query and "roda" in query:
            if contract_present:
                content = (
                    "UNKNOWN: jumlah roda tidak dapat ditentukan tanpa "
                    "jumlah roda per gerbong."
                )
            else:
                content = "10 gerbong x 8 roda = 80 roda."
        elif "95" in query and "setengah" in query:
            if contract_present:
                content = (
                    "95 / 2 = 47.5. Ini hasil aritmetika literal, tetapi "
                    "tidak konsisten sebagai jumlah entitas diskret; perlu "
                    "klarifikasi, dan saya tidak membulatkannya."
                )
            else:
                content = "Hasilnya 47.5 penumpang."
        else:
            if contract_present:
                content = "12 - 3 + 5 = 14 penumpang."
            else:
                content = "Saya perlu sumber eksternal untuk memverifikasi hitungan itu."
        # Proof records exercise the real gate. The old train fixture's
        # capacity-derived minimum did not establish an actual entity count.
        if contract_present:
            record = {"facts": [], "calculations": [], "unknowns": [], "examples": []}
            if "stasiun a" in query:
                record["calculations"] = [
                    {"expression": "100 - 20 + 15", "result": "95"},
                    {"expression": "half(r0)", "result": "47.5"},
                    {"expression": "r1 + pair(5)", "result": "57.5"},
                ]
                record["unknowns"] = ["jumlah gerbong aktual", "jumlah roda per gerbong"]
            elif "gerbong" in query and "roda" in query:
                record["unknowns"] = ["jumlah roda per gerbong"]
            elif "95" in query and "setengah" in query:
                record["calculations"] = [{"expression": "half(95)", "result": "47.5"}]
            else:
                record["calculations"] = [{"expression": "12 - 3 + 5", "result": "14"}]
            content = json.dumps(record)
        return {"content": content}


class DirectAnswerSemanticsTests(unittest.TestCase):
    def run_direct(self, query, router=None):
        counters = {name: 0 for name in ("planner", "search", "fetch", "facts", "kg")}
        llm = ScriptedLLM()
        agent = AranAgent.__new__(AranAgent)
        agent.router = router or DirectRouter()
        agent.skill_router = SimpleNamespace(select=lambda _goal: None)
        agent.user_memory = SimpleNamespace(search=lambda _goal: [])
        agent.llm = llm
        agent.task_planner = Trap(counters, "planner")
        agent.searcher = Trap(counters, "search")
        agent.skill_bridge = Trap(counters, "fetch")
        agent.facts = Trap(counters, "facts")
        with patch.object(orchestrator, "TokenProfiler", lambda: object()), \
             patch.object(orchestrator, "LatencyProfiler", lambda: object()), \
             patch.object(orchestrator, "log_event", lambda *a, **k: None), \
             patch.object(orchestrator, "init_request_id", lambda: "direct-test"), \
             patch.object(orchestrator, "KnowledgeGraph", lambda: self.fail_kg(counters)):
            answer = agent.research(query)
        return answer, llm, counters

    @staticmethod
    def fail_kg(counters):
        counters["kg"] += 1
        raise AssertionError("unexpected KnowledgeGraph construction")

    def assert_contract(self, llm):
        self.assertEqual(len(llm.calls), 1)
        prompt = llm.calls[0][0]
        self.assertTrue(has_direct_semantic_contract(prompt), prompt)

    def assert_zero_pipeline(self, counters):
        self.assertEqual(counters, {"planner": 0, "search": 0, "fetch": 0, "facts": 0, "kg": 0})

    def test_case1_complete_arithmetic_is_derived_without_sources(self):
        answer, llm, counters = self.run_direct(
            "Ada 12 penumpang. 3 turun lalu 5 naik. Berapa jumlahnya sekarang?",
            router=SemanticRouter(),
        )
        self.assertIn("14", answer)
        self.assertNotIn("sumber", answer.casefold())
        self.assert_contract(llm)
        self.assert_zero_pipeline(counters)

    def test_case2_missing_wheels_is_unknown(self):
        answer, llm, counters = self.run_direct(
            "10 gerbong. Jumlah roda lokomotif tidak dihitung. "
            "Berapa total roda kereta?"
        )
        self.assertIn("UNKNOWN", answer)
        self.assertNotIn("8 roda", answer.casefold())
        self.assert_contract(llm)
        self.assert_zero_pipeline(counters)

    def test_case3_fractional_discrete_count_is_flagged(self):
        answer, llm, counters = self.run_direct(
            "Ada 95 penumpang. Jumlahnya berkurang setengahnya. "
            "Berapa hasil hitung penumpang?"
        )
        self.assertIn("47.5", answer)
        self.assertRegex(answer.casefold(), r"tidak konsisten|diskret|klarifikasi")
        self.assertNotRegex(answer.casefold(), r"47\s*(orang|penumpang)")
        self.assert_contract(llm)
        self.assert_zero_pipeline(counters)

    def test_case4_missing_input_with_now_stays_direct_and_unknown(self):
        answer, llm, counters = self.run_direct(
            "10 gerbong. Jumlah roda lokomotif tidak dihitung. "
            "Berapa total roda kereta sekarang?"
        )
        self.assertIn("UNKNOWN", answer)
        self.assertNotIn("8 roda", answer.casefold())
        self.assert_contract(llm)
        self.assert_zero_pipeline(counters)

    def test_case5_explicit_external_request_is_research(self):
        route = SemanticRouter().route(
            "cari berapa jumlah roda yang umum dipakai satu gerbong kereta"
        )
        self.assertEqual(route.mode, "research")

    def test_exact_audited_train_query_is_router_direct_and_pipeline_free(self):
        answer, llm, counters = self.run_direct(TRAIN_QUERY, router=SemanticRouter())
        self.assertIn("47.5", answer)
        self.assertIn("57.5", answer)
        self.assertRegex(answer.casefold(), r"tidak konsisten|diskret")
        self.assertRegex(answer.casefold(), r"tidak dapat ditentukan|unknown")
        self.assertNotIn("8 roda", answer.casefold())
        self.assertNotIn("2 gerbong", answer.casefold())
        self.assertIn("jumlah gerbong aktual", answer.casefold())
        self.assert_contract(llm)
        self.assert_zero_pipeline(counters)

    def test_router_regression_cases(self):
        router = SemanticRouter()
        expected = {
            "5+5": "direct",
            "5+5 sekarang": "direct",
            "speaker ACR 12500 black": "research",
            "berapa harga emas sekarang?": "research",
            "MikroTik RB5009 product specs": "research",
            TRAIN_QUERY: "direct",
        }
        for query, mode in expected.items():
            with self.subTest(query=query[:40]):
                self.assertEqual(router.route(query).mode, mode)


if __name__ == "__main__":
    unittest.main()

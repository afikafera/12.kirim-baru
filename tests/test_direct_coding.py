"""Coding routing/output regressions; scripted providers only, no live calls."""
import ast
import json
import socket
import unittest
from unittest.mock import patch
from hermes_agent.semantic_router import SemanticRouter
from hermes_agent.direct_answer_grounding import validate_and_render
from hermes_agent.direct_provider_recovery import DirectProviderFailure
import test_direct_answer_grounding as fixture

CODE = "def tambah(a, b):\n    return a + b\n"
FENCED = chr(96) * 3 + "python\n" + CODE + chr(96) * 3
QUERY = "Tulis fungsi Python untuk menjumlahkan dua bilangan."


class CodingRoutingTests(unittest.TestCase):
    def test_self_contained_generation_and_fix(self):
        queries = [
            "Buat fungsi Python tambah",
            QUERY,
            "Jika daftar kosong, fungsi Python harus mengembalikan nol. Buat implementasinya.",
            "Perbaiki kode berikut: def tambah(a, b): return a - b. Fungsi harus menjumlahkan kedua argumen.",
            "Buat endpoint API lokal yang mengembalikan teks hello.",
            "Show me a code snippet of a website's sticky header in CSS and JavaScript.",
            "Write a JavaScript function to sort a list of numbers.",
            "Refactor this Python function to remove duplicated logic.",
        ]
        for query in queries:
            with self.subTest(query=query):
                route = SemanticRouter().route(query)
                self.assertEqual((route.mode, route.reason), ("direct", "coding"))

    def test_external_coding_stays_research(self):
        for query in [
            "Cari contoh kode Python dari web",
            "Buat kode Python mengikuti dokumentasi resmi terbaru",
            "Write code based on https://example.com/docs",
            "Buat integrasi API Stripe sesuai dokumentasi resmi",
            "Bandingkan benchmark library Python terbaru lalu buat kode",
        ]:
            with self.subTest(query=query):
                self.assertEqual(SemanticRouter().route(query).mode, "research")

    def test_code_payload_does_not_create_external_intent(self):
        query = "Perbaiki kode Python berikut:\n" + chr(96)*3 + "python\napi = 'https://example.com/docs'\n" + chr(96)*3
        self.assertEqual(SemanticRouter().route(query).reason, "coding")

    def test_non_coding_and_memory_keep_existing_contract(self):
        for query in ["5+5", "Buat fungsi kuadrat dari tiga titik", "Jangan buat kode. Hitung 5+5.",
                      "Terjemahkan buat kode ke bahasa Inggris", "Ingat bahwa saya memakai Python"]:
            with self.subTest(query=query):
                self.assertNotEqual(SemanticRouter().route(query).reason, "coding")
        self.assertEqual(SemanticRouter().route("spesifikasi JBL PartyBox").mode, "research")
        self.assertEqual(SemanticRouter().route("Ingat bahwa saya memakai Python").mode, "memory")

    def test_local_search_code_is_direct(self):
        self.assertEqual(SemanticRouter().route(
            "Write Python code to search local files by name.").reason, "coding")

    def test_raw_text_expression_is_not_code_answer(self):
        from hermes_agent.direct_coding import validate_code_answer
        with self.assertRaisesRegex(ValueError, "missing_code_block"):
            validate_code_answer("not code", QUERY)

    def test_non_programming_code_words_do_not_select_coding(self):
        for query in ["Tulis kode pos Jakarta", "Buat kode promo diskon", "Buat kode voucher belanja"]:
            with self.subTest(query=query):
                self.assertNotEqual(SemanticRouter().route(query).reason, "coding")
        self.assertEqual(SemanticRouter().route(
            "Buat fungsi Python untuk menghasilkan kode promo").reason, "coding")


class CodingOutputTests(unittest.TestCase):
    def validate(self, content, goal=QUERY):
        from hermes_agent.direct_coding import validate_code_answer
        return validate_code_answer(content, goal)

    def test_python_is_syntax_checked_and_retained(self):
        answer = self.validate(FENCED)
        self.assertIn(CODE, answer)
        self.assertIn("Sintaks Python diperiksa", answer)
        self.assertIn("belum dijalankan", answer)
        ast.parse(CODE)
        namespace = {}
        exec(compile(CODE, "<test-only>", "exec"), namespace)
        for a, b, expected in [(2, 3, 5), (-2, 3, 1), (0, 0, 0), (0.5, 0.25, 0.75)]:
            self.assertEqual(namespace["tambah"](a, b), expected)

    def test_raw_python_is_wrapped(self):
        self.assertIn(FENCED, self.validate(CODE))

    def test_invalid_python_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_python_syntax"):
            self.validate(chr(96)*3 + "python\ndef broken(:\n" + chr(96)*3)

    def test_never_executes_generated_code(self):
        text = chr(96)*3 + "python\nraise RuntimeError('must not execute')\n" + chr(96)*3
        self.assertIn("raise RuntimeError", self.validate(text))

    def test_python_label_cannot_be_skipped(self):
        with self.assertRaisesRegex(ValueError, "missing_python_block"):
            self.validate(chr(96)*3 + "text\ndef broken(:\n" + chr(96)*3)

    def test_other_languages_are_not_claimed_syntax_verified(self):
        answer = self.validate(chr(96)*3 + "javascript\nconst add = (a,b) => a+b;\n" + chr(96)*3,
                               "Write JavaScript code to add two numbers")
        self.assertIn("Sintaks bahasa lain belum diperiksa", answer)
        self.assertIn("belum dijalankan", answer)

    def test_incomplete_fence_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete_code_fence"):
            self.validate(chr(96)*3 + "python\n" + CODE)

    def test_no_code_and_empty_code_rejected(self):
        for text in ["Jawabannya adalah lima.", chr(96)*3+"python\n\n"+chr(96)*3]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.validate(text)

    def test_limits_and_null_rejected(self):
        for text in [None, "x" * 32001, FENCED + "\x00"]:
            with self.subTest(text_type=type(text).__name__), self.assertRaises(ValueError):
                self.validate(text)

    def test_arithmetic_validator_still_rejects_code(self):
        with self.assertRaises(ValueError):
            validate_and_render(FENCED, "5+5", "5+5")


class CodingIntegrationTests(unittest.TestCase):
    def run_code(self, outputs, multi=False):
        helper = fixture.DirectGroundingTests("test_exact_captured_train_output_cannot_escape")
        self.helper = helper
        # Real router + real orchestrator; external systems are traps in helper.
        with patch.object(fixture, "DirectRouter", SemanticRouter), \
             patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            return helper.run_direct(QUERY, outputs, multi_model=multi)

    def test_two_aliases_accept_without_repair(self):
        for multi in [False, True]:
            with self.subTest(multi=multi):
                answer, llm = self.run_code([FENCED], multi)
                self.assertIn(CODE, answer)
                self.assertEqual(len(llm.calls), 1)
                self.assertNotIn("exact user excerpt", llm.calls[0]["system_prompt"])
                self.assertIn("CODING", llm.calls[0]["system_prompt"])

    def test_invalid_python_repairs_once(self):
        answer, llm = self.run_code([chr(96)*3+"python\ndef broken(:\n"+chr(96)*3, FENCED])
        self.assertIn(CODE, answer)
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("invalid_python_syntax", llm.calls[1]["user_query"])

    def test_exhausted_invalid_output_is_technical_error(self):
        with self.assertRaises(DirectProviderFailure) as caught:
            self.run_code(["not code", "not code"])
        self.assertEqual(caught.exception.failure_class, "DIRECT_OUTPUT_INVALID")
        self.assertEqual(caught.exception.status_code, 502)
        self.assertNotIn("UNKNOWN", caught.exception.public_error()["message"])
        self.assertEqual(len(self.helper.last_llm.calls), 2)

    def test_repair_provider_failure_is_preserved(self):
        with self.assertRaises(DirectProviderFailure) as caught:
            self.run_code(["not code", RuntimeError("unsupported model")])
        self.assertEqual(caught.exception.failure_class, "TERMINAL_REQUEST_FAILURE")

    def test_truncation_is_not_released(self):
        from hermes_agent.direct_coding import enforce_code_answer
        llm = fixture.ScriptedLLM([FENCED])
        answer = enforce_code_answer(llm, {"content": FENCED, "finish_reason": "length"},
                                     goal=QUERY, user_query=QUERY, request_id="offline-code")
        self.assertIn(CODE, answer)
        self.assertEqual(len(llm.calls), 1)
        self.assertIn("truncated_output", llm.calls[0]["user_query"])


if __name__ == "__main__":
    unittest.main()

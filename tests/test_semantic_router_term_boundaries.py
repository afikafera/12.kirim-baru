"""Router regression only: no provider, research, service or KG calls."""
import unittest
from hermes_agent.semantic_router import SemanticRouter

EXACT_USER_QUERY = "Sebuah kereta memiliki 95 penumpang. Setelah itu jumlah penumpang berkurang setengahnya.\n\nBerapa jumlah penumpang sekarang?\n\nKereta tersebut memiliki beberapa gerbong, tetapi jumlah gerbong dan jumlah roda per gerbong tidak diberikan.\n\nBerapa total roda kereta?"


class ExternalTermBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.router = SemanticRouter()

    def test_exact_user_query_is_direct(self):
        result = self.router.route(EXACT_USER_QUERY)
        self.assertEqual(result.mode, "direct")
        self.assertEqual(result.reason, "self_contained_reasoning")

    def test_without_temporal_adverb_is_still_direct(self):
        self.assertEqual(self.router.route(EXACT_USER_QUERY.replace(" sekarang", "")).mode, "direct")

    def test_other_self_contained_problems_with_embedded_api_stay_direct(self):
        queries = (
            "Ada 95 sapi. Jumlahnya berkurang setengahnya. Berapa jumlah sapi sekarang?",
            "Ada 100 koin, tetapi jumlahnya berkurang setengahnya. Berapa jumlahnya sekarang?",
            "Modal kapital 100 berkurang setengahnya. Berapa total sekarang?",
            "Diberitahu ada 95 orang. Setelah berkurang setengahnya, berapa jumlah sekarang?",
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertEqual(self.router.route(query).mode, "direct")

    def test_embedded_keywords_are_not_external_terms(self):
        for word in ("tetapi", "sapi", "diapit", "kapital", "priceless", "diberitahu", "xAPIx", "préAPIpost"):
            with self.subTest(word=word):
                self.assertFalse(self.router._looks_like_external_lookup(word))

    def test_real_api_lookups_remain_research(self):
        for query in (
            "Jelaskan dokumentasi API resmi layanan tersebut.",
            "Bagaimana autentikasi REST API bekerja menurut dokumentasi resmi?",
            "Periksa API/v1 dan batas permintaannya.",
            "Periksa API-v2 dan batas permintaannya.",
            "Periksa APIs yang tersedia pada layanan tersebut.",
        ):
            with self.subTest(query=query):
                self.assertEqual(self.router.route(query).mode, "research")

    def test_common_english_plural_lookups_remain_research(self):
        for term in ("prices", "specifications", "reviews", "releases", "APIs"):
            with self.subTest(term=term):
                self.assertTrue(self.router._looks_like_external_lookup(term))
                self.assertEqual(self.router.route("Periksa " + term + " perangkat tersebut.").mode, "research")

    def test_multiword_external_terms_allow_whitespace(self):
        for query in ("Apa jadwal hari ini?", "Apa jadwal hari\tini?", "Apa jadwal hari\nini?"):
            with self.subTest(query=query):
                self.assertTrue(self.router._looks_like_external_lookup(query))

    def test_keyword_case_and_punctuation_preserve_research(self):
        for query in ("[API]", "(api)", "API: endpoint", "Periksa SPECIFICATION.", "REVIEW perangkat tersebut"):
            with self.subTest(query=query):
                self.assertTrue(self.router._looks_like_external_lookup(query))

    def test_external_dependency_precedence_is_preserved(self):
        for query in (
            "Ada 95 panggilan, tetapi periksa API resmi untuk batas hari ini.",
            "Sebuah kereta membawa 95 orang. Cari spesifikasi gerbong dan jumlah roda.",
            "Hitung perubahan harga Bitcoin sekarang dengan data terbaru.",
        ):
            with self.subTest(query=query):
                self.assertEqual(self.router.route(query).mode, "research")

    def test_existing_basic_math_and_product_routes_are_preserved(self):
        for query, mode in (
            ("5+5", "direct"),
            ("5+5 sekarang", "direct"),
            ("berapa harga emas sekarang?", "research"),
            ("speaker ACR 12500 black", "research"),
        ):
            with self.subTest(query=query):
                self.assertEqual(self.router.route(query).mode, mode)


if __name__ == "__main__":
    unittest.main()

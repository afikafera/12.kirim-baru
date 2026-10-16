"""Router coverage for under-specified and fractional self-contained queries."""
import unittest

from hermes_agent.semantic_router import SemanticRouter


class MissingInputFractionalRoutingTests(unittest.TestCase):
    def setUp(self):
        self.router = SemanticRouter()

    def assert_direct(self, query):
        with self.subTest(query=query):
            result = self.router.route(query)
            self.assertEqual(result.mode, "direct", (result.mode, result.reason))
            self.assertTrue(self.router._is_self_contained_reasoning(query))

    def test_missing_required_input_forms_are_direct(self):
        queries = (
            "10 gerbong. Jumlah roda lokomotif tidak dihitung. "
            "Berapa total roda kereta?",
            "10 gerbong. Jumlah roda lokomotif tidak dihitung. "
            "Berapa total roda kereta sekarang?",
        )
        for query in queries:
            self.assert_direct(query)

    def test_fractional_discrete_result_forms_are_direct(self):
        queries = (
            "Ada 95 penumpang. Jumlahnya berkurang setengahnya. "
            "Berapa hasil hitung penumpang?",
            "Ada 95 penumpang. Jumlahnya berkurang setengahnya. "
            "Berapa hasil hitung penumpang sekarang?",
        )
        for query in queries:
            self.assert_direct(query)

    def test_genuine_external_and_product_lookups_remain_research(self):
        queries = (
            "cari berapa jumlah roda yang umum dipakai satu gerbong kereta",
            "berapa harga emas sekarang",
            "speaker ACR 12500 black",
            "MikroTik RB5009 product specs",
        )
        for query in queries:
            with self.subTest(query=query):
                result = self.router.route(query)
                self.assertEqual(result.mode, "research", (result.mode, result.reason))


if __name__ == "__main__":
    unittest.main()

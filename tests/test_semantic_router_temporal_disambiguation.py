import unittest

from hermes_agent.semantic_router import SemanticRouter


class TestSemanticRouterTemporalDisambiguation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = SemanticRouter()

    def assert_mode(self, query, expected):
        result = self.router.route(query)
        self.assertEqual(result.mode, expected, f"{query!r}: {result!r}")

    def test_a_exact_self_contained_train_arithmetic(self):
        query = (
            "Sebuah kereta berangkat dari stasiun A membawa 100 penumpang. "
            "Di stasiun B, 20 orang turun dan 15 orang naik. "
            "Di stasiun C, jumlah penumpang berkurang setengahnya. "
            "Di stasiun D, 5 pasang suami istri naik. "
            "Berapa jumlah penumpang sekarang dan berapa jumlah total roda "
            "kereta jika setiap gerbong diisi maksimal 40 orang?"
        )
        self.assert_mode(query, "direct")

    def test_b_arithmetic_with_sekarang(self):
        self.assert_mode("5+5 sekarang", "direct")

    def test_c_current_gold_price(self):
        self.assert_mode("berapa harga emas sekarang?", "research")

    def test_d_plain_arithmetic(self):
        self.assert_mode("5+5", "direct")

    def test_e_speaker_acr_product_lookup(self):
        self.assert_mode("speaker ACR 12500 black", "research")

    def test_f_other_product_lookup(self):
        self.assert_mode("MikroTik hAP ax3 specs", "research")

    def test_g_current_bitcoin_price(self):
        self.assert_mode("What is the current price of Bitcoin today?", "research")

    def test_h_explicit_research_for_carriage_wheels(self):
        self.assert_mode(
            "Research the typical number of wheels per railway carriage",
            "research",
        )


if __name__ == "__main__":
    unittest.main()

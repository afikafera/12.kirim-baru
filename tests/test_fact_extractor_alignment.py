"""Temporary transport copy for the active-VM FactChecker regression test."""

import unittest

from hermes_agent.fact_checker import FactChecker


DATASHEET_URL = "https://acrspeaker.com/uploads/productdatasheet/3MN0689-00-ACR-12500-BLACK-GENERAL-SPEC_compressed.pdf"

ACR_TEXT = """## Specifications
12 Inch Woofer - ACR
Diameter Speaker Impedansi Max. Power Lebar Daerah Frekuensi Sensitivity (2.83 V / 1 m) Diameter Cone Efektif Medan Magnet Berat Magnet Material Magnet Diameter Voice Coil Material Voice Coil Berat Speaker
12 inch / 304.8 mm
8 Ω 450 Watt 55 Hz - 6000 Hz 97 dB 256 mm 1.13 T 1.04 kg/36.68 Oz Ferrite 49.5 mm/1.9 inch TILL 3.1 kg
Parameter “Thiele-Small”
Frekuensi Resonansi / Fs DCR Qts Qes Qms Mms Cms BL Product Vas No Sd Xmax
55 Hz 5.6 Ω 0.76 0.84 7.86 47 g 0.17 mm/N 10.5 Tm 63.8 liters 1.29% 514.7 cm² 5.65 mm
Referensi Box Speaker
129 Lt pada Fb 55 Hz, Tebal Material 15 mm
"""


class AlignmentAwareLLM:
    """Deterministic stand-in: models the known bad output unless the prompt
    explicitly requires one-to-one alignment of labeled table fields.
    """

    def __init__(self):
        self.prompt = None

    def analyze(self, system, prompt, temperature=0.1, max_tokens=None):
        self.prompt = prompt
        if "one key per distinct labeled field" in prompt.lower():
            content = {
                "source_url": DATASHEET_URL,
                "source_type": "datasheet",
                "no": "1.29%",
                "sd": "514.7 cm²",
                "xmax": "5.65 mm",
                "speaker_weight": "3.1 kg",
                "box_reference": "129 Lt pada Fb 55 Hz, Tebal Material 15 mm",
            }
        else:
            content = {
                "source_url": DATASHEET_URL,
                "source_type": "datasheet",
                "no_sd": "1.29%",
                "xmax": "514.7 cm²",
                "thiele_small_parameter": "5.65 mm",
                "voice_coil_weight": "3.1 kg",
                "material_thickness": "15 mm",
            }
        import json
        return {
            "content": json.dumps(content, ensure_ascii=False),
            "tokens_input": 1,
            "tokens_output": 1,
            "api_cost": 0,
        }


def test_acr_datasheet_table_fields_stay_aligned():
    llm = AlignmentAwareLLM()
    checker = FactChecker(llm)
    facts, _ = checker.extract_facts_batch(
        [{"url": DATASHEET_URL, "doc_type": "datasheet", "content": ACR_TEXT}],
        [{"field_id": "speaker_specs", "label": "ACR 12500 technical specifications"}],
    )

    assert facts["no"]["value"] == "1.29%"
    assert facts["sd"]["value"] == "514.7 cm²"
    assert facts["xmax"]["value"] == "5.65 mm"
    assert facts["speaker_weight"]["value"] == "3.1 kg"
    assert "no_sd" not in facts
    assert facts["xmax"]["value"] != "514.7 cm²"
    assert "thiele_small_parameter" not in facts
    assert "voice_coil_weight" not in facts
    assert "material_thickness" not in facts
    assert "box_reference" in facts
    assert "15 mm" in facts["box_reference"]["value"]


class NestedWrapperLLM:
    def __init__(self, payload):
        import json
        self.content = json.dumps(payload)

    def analyze(self, *args, **kwargs):
        return {"content": self.content, "tokens_input": 1, "tokens_output": 1, "api_cost": 0}


class FactExtractorNestedWrapperTests(unittest.TestCase):
    URL = "https://example.test/status-codes"
    EVIDENCE = [{"url": URL, "doc_type": "documentation", "content": "200 OK succeeded. 303 See Other redirects. 404 Not Found. 500 Internal Server Error."}]

    def test_nested_wrapper_description_facts_all_normalize(self):
        from hermes_agent.fact_checker import FactChecker
        payload = {"http_status_codes": {
            key: {"description": description, "source": self.URL, "source_type": "documentation"}
            for key, description in {
                "http_200": "The request succeeded.",
                "http_303": "The response redirects to another resource.",
                "http_404": "The requested resource was not found.",
                "http_500": "The server encountered an unexpected condition.",
            }.items()
        }}
        facts, _ = FactChecker(NestedWrapperLLM(payload)).extract_facts_batch(
            self.EVIDENCE, [{"field_id": "http_status_codes", "label": "HTTP status codes"}]
        )
        self.assertEqual(set(facts), {"http_200", "http_303", "http_404", "http_500"})
        self.assertEqual(facts["http_200"]["value"], "The request succeeded.")
        self.assertEqual(facts["http_303"]["source"], self.URL)
        self.assertEqual(facts["http_500"]["source_type"], "documentation")

    def test_canonical_value_payload_remains_unchanged(self):
        from hermes_agent.fact_checker import FactChecker
        payload = {"http_200": {"value": "The request succeeded.", "source": self.URL, "source_type": "documentation"}}
        facts, _ = FactChecker(NestedWrapperLLM(payload)).extract_facts_batch(
            self.EVIDENCE, [{"field_id": "http_200", "label": "HTTP 200"}]
        )
        self.assertEqual(facts["http_200"]["value"], "The request succeeded.")
        self.assertEqual(facts["http_200"]["source"], self.URL)
        self.assertEqual(facts["http_200"]["source_type"], "documentation")

    def test_malformed_nested_objects_are_not_promoted(self):
        from hermes_agent.fact_checker import FactChecker
        payload = {"wrapper": {
            "missing_source": {"description": "Not a fact without provenance."},
            "metadata": {"title": "HTTP status page", "url": self.URL},
            "empty": {"description": "", "source": self.URL},
            "untrusted": {"description": "Unverified fact.", "source": "https://other.test/"},
        }}
        facts, _ = FactChecker(NestedWrapperLLM(payload)).extract_facts_batch(
            self.EVIDENCE, [{"field_id": "http_status_codes", "label": "HTTP status codes"}]
        )
        self.assertEqual(facts, {})

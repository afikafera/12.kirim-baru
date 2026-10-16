import os
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from aran_search.evidence import DocumentIntelligence
from aran_search.evidence.classifier import Classifier
from aran_search.searcher import AgentReachSearcher
from aran_search.evidence.normalizer import Normalizer
from aran_search.evidence.section_engine import SectionEngine, _has_markdown_table, _truncate_preserving_table
from difflib import SequenceMatcher


def _legacy_docintel_process(raw_content: str, query: str) -> dict:
    """Reference implementation of pre-patch DocumentIntelligence for byte-for-byte invariance check."""
    normalizer = Normalizer()
    clf = Classifier()
    se = SectionEngine()

    normalized = normalizer.normalize(raw_content)
    if not normalized:
        doc_type = "general"
    elif clf.OFFICIAL_API.search(normalized):
        doc_type = "official_docs"
    elif clf.YOUTUBE_URL.search(normalized):
        doc_type = "video"
    else:
        headings = len(clf.HEADING.findall(normalized))
        kvs = len(clf.KV_LINE.findall(normalized))
        if kvs >= 8:
            doc_type = "datasheet"
        elif headings >= 4:
            doc_type = "documentation"
        elif headings >= 1 and len(normalized) > 800:
            doc_type = "article"
        else:
            doc_type = "general"

    matches = list(se.HEADING.finditer(normalized))
    if not matches:
        all_sections = [{"heading": "", "text": normalized, "kvs": dict(se.KV_LINE.findall(normalized))}]
    else:
        all_sections = []
        for i, match in enumerate(matches):
            heading = match.group(1)
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(normalized)
            text = normalized[start:end].strip()
            kvs = dict(se.KV_LINE.findall(text))
            all_sections.append({"heading": heading, "text": text, "kvs": kvs})

    relevant = [s for s in all_sections if not se.is_boilerplate(s["heading"], s["text"])]
    scored = [(se.score_section(s["heading"], s["text"], s["kvs"], query), s) for s in relevant]
    scored.sort(key=lambda x: x[0], reverse=True)

    output = []
    total_chars = 0
    all_kvs = {}
    max_sections = 8
    max_chars = 6000
    for score, s in scored:
        if score < 0.05 and len(output) > 0:
            break
        haystack_full = (s["heading"] + " " + s["text"]).lower()
        has_ts = se._has_ts_marker(haystack_full)
        is_single_table = len(scored) == 1 and _has_markdown_table(s["text"])
        if is_single_table:
            headroom = 400 if s["kvs"] else 50
            section_cap = min(max_chars - headroom, 5000)
        elif has_ts:
            section_cap = 2000
        else:
            section_cap = 1000
        section_text = _truncate_preserving_table(s["text"], section_cap)
        output.append(f"## {s['heading']}\n{section_text}")
        all_kvs.update(s["kvs"])
        total_chars += len(section_text)
        if len(output) >= max_sections or total_chars >= max_chars:
            break
    if all_kvs:
        kv_text = "\n".join([f"{k}: {v}" for k, v in list(all_kvs.items())[:30]])
        output.insert(0, f"## Specifications\n{kv_text}")

    formatted = "\n\n".join(output)
    return {
        "formatted": formatted,
        "doc_type": doc_type,
        "sections_total": len(all_sections),
        "sections_kept": formatted.count("## "),
        "char_before": len(raw_content),
        "char_after": len(formatted),
    }


class TestEvidenceDocIntelRegression(unittest.TestCase):
    def setUp(self):
        self.docintel = DocumentIntelligence()

    # ------------------------------------------------------------------
    # 1. SOURCE CODE (Multi-language & Generic)
    # ------------------------------------------------------------------
    def test_source_code_python_not_classified_as_datasheet(self):
        py_code = (
            "import os\n"
            "import json\n"
            "from urllib.parse import urlparse\n\n"
            "class DataProcessor:\n"
            "    DEFAULT_MODE: str = 'strict'\n"
            "    MAX_RETRIES: int = 3\n\n"
            "    def __init__(self, config: dict):\n"
            "        self.config = config\n"
            "        self.label = f'Processor: {config.get(\"name\", \"default\")}'\n"
            "        self.owner = f'Owner: {config.get(\"owner\", \"system\")}'\n"
            "        self.status = f'Status: {config.get(\"status\", \"ready\")}'\n"
            "        self.region = f'Region: {config.get(\"region\", \"ap-southeast\")}'\n"
            "        self.tier = f'Tier: {config.get(\"tier\", \"production\")}'\n"
            "        self.version = f'Version: {config.get(\"version\", \"1.0\")}'\n"
            "        self.timeout = f'Timeout: {config.get(\"timeout\", 30)}'\n"
            "        self.retries = f'Retries: {config.get(\"retries\", 3)}'\n"
            "        self.format = f'Format: {config.get(\"format\", \"json\")}'\n\n"
            "    def compute_checksum_digest(self, payload: bytes) -> str:\n"
            "        \"\"\"Compute canonical SHA-256 digest after normalizing line endings.\"\"\"\n"
            "        normalized = payload.replace(b'\\r\\n', b'\\n')\n"
            "        return f'sha256:{len(normalized)}'\n"
        )
        res = self.docintel.process(
            py_code,
            "How does compute_checksum_digest normalize payload and return digest?",
            url="https://example.org/repo/blob/main/pkg/processor.py",
        )
        self.assertEqual(res["doc_type"], "source_code")
        self.assertNotIn("## Specifications", res["formatted"])
        self.assertIn("def compute_checksum_digest", res["formatted"])
        self.assertIn("payload.replace", res["formatted"])

    def test_source_code_go_and_typescript_without_url(self):
        go_code = (
            "package tokenbucket\n\n"
            "import (\n"
            "    \"sync\"\n"
            "    \"time\"\n"
            ")\n\n"
            "type Limiter struct {\n"
            "    mu sync.Mutex\n"
            "    rate float64\n"
            "    burst int\n"
            "}\n\n"
            "func (l *Limiter) AllowRequest(now time.Time, tokens int) bool {\n"
            "    l.mu.Lock()\n"
            "    defer l.mu.Unlock()\n"
            "    return tokens <= l.burst\n"
            "}\n"
        )
        res_go = self.docintel.process(go_code, "AllowRequest token bucket burst check", url="")
        self.assertEqual(res_go["doc_type"], "source_code")
        self.assertIn("func (l *Limiter) AllowRequest", res_go["formatted"])

        ts_code = (
            "import { Request, Response } from 'express';\n\n"
            "export class AuthMiddleware {\n"
            "    constructor(private readonly secret: string) {}\n"
            "}\n\n"
            "export async function verifyBearerToken(header: string): Promise<boolean> {\n"
            "    if (!header.startsWith('Bearer ')) {\n"
            "        return false;\n"
            "    }\n"
            "    return header.length > 16;\n"
            "}\n"
        )
        res_ts = self.docintel.process(ts_code, "verifyBearerToken Bearer header validation", url="")
        self.assertEqual(res_ts["doc_type"], "source_code")
        self.assertIn("export async function verifyBearerToken", res_ts["formatted"])

    # ------------------------------------------------------------------
    # 2. LONG ARTICLE (Artikel Panjang) & Non-Source-Code Invariance
    # ------------------------------------------------------------------
    def test_long_article_truncation_and_invariance(self):
        intro_body = ("Modern distributed consensus systems rely on replicated state machines. " * 25).strip()
        deep_body = (
            "Leader lease renewal requires a quorum heartbeat ack within election_timeout / 2. "
            + ("Additional commentary on clock drift bounds and network partitions. " * 25)
        ).strip()
        article_doc = (
            f"# Consensus Architecture Overview\n{intro_body}\n\n"
            f"## Leader Lease Renewal Mechanism\n{deep_body}\n"
        )
        query = "Leader lease renewal quorum heartbeat election_timeout"
        actual = self.docintel.process(article_doc, query, url="https://example.com/blog/consensus")
        expected = _legacy_docintel_process(article_doc, query)

        self.assertEqual(actual["doc_type"], "article")
        self.assertEqual(actual, expected)
        self.assertIn("## Leader Lease Renewal Mechanism", actual["formatted"])
        self.assertLessEqual(len(actual["formatted"]), 2500)

    # ------------------------------------------------------------------
    # 3. DOCUMENTATION (Dokumentasi dengan Fenced Code Block)
    # ------------------------------------------------------------------
    def test_documentation_with_code_fence_not_misclassified_as_source_code(self):
        doc_content = (
            "# HTTP Client SDK Documentation\n"
            "Welcome to the official HTTP Client SDK guide.\n\n"
            "## Installation\n"
            "Install the package via pip or uv in your virtual environment.\n\n"
            "## Configuration\n"
            "Set timeout and retry policy using the ClientConfig object.\n\n"
            "## Retry Backoff Policy\n"
            "Exponential backoff uses base_delay=0.5s with jitter factor 0.25 up to max_attempts=5.\n\n"
            "## Code Example\n"
            "```python\n"
            "from sdk.client import HttpClient\n"
            "import asyncio\n\n"
            "async def run_example():\n"
            "    client = HttpClient(timeout=10)\n"
            "    return await client.get('https://example.com')\n"
            "```\n"
        )
        query = "Retry backoff policy base_delay jitter max_attempts"
        actual = self.docintel.process(doc_content, query, url="https://docs.example.com/sdk/guide")
        expected = _legacy_docintel_process(doc_content, query)

        self.assertEqual(actual["doc_type"], "documentation")
        self.assertEqual(actual, expected)
        self.assertIn("base_delay=0.5s", actual["formatted"])

    # ------------------------------------------------------------------
    # 4. DATASHEET / MARKDOWN TABLE / THIELE-SMALL PARAMETERS
    # ------------------------------------------------------------------
    def test_datasheet_and_table_and_thiele_small_invariance(self):
        # 4a. Datasheet with >= 8 KVs and Thiele-Small Xmax
        datasheet_doc = (
            "# PD.1850 Loudspeaker Specifications\n"
            "Nominal Diameter: 460 mm (18 in)\n"
            "Power Rating: 800 Watts\n"
            "Nominal Impedance: 8 Ohms\n"
            "Sensitivity: 98 dB\n"
            "Frequency Range: 35-2000 Hz\n"
            "Voice Coil Diameter: 127 mm\n"
            "Magnet Type: Ceramic\n"
            "Resonance Fs: 33 Hz\n"
            "Mechanical Factor Qms: 4.92\n"
            "Electrical Factor Qes: 0.29\n"
            "Total Factor Qts: 0.27\n"
            "Maximum Linear Excursion Xmax: 5.65 mm\n"
        )
        query_ds = "PD.1850 Thiele-Small Fs Qts Xmax specifications"
        actual_ds = self.docintel.process(datasheet_doc, query_ds, url="https://specs.example.com/pd1850")
        expected_ds = _legacy_docintel_process(datasheet_doc, query_ds)

        self.assertEqual(actual_ds["doc_type"], "datasheet")
        self.assertEqual(actual_ds, expected_ds)
        self.assertIn("## Specifications", actual_ds["formatted"])
        self.assertIn("5.65 mm", actual_ds["formatted"])

        # 4b. Single Markdown table preservation up to 5000 cap
        rows = ["| Parameter | Symbol | Value | Unit |", "| --- | --- | --- | --- |"]
        for i in range(1, 55):
            rows.append(f"| Spec Parameter {i:02d} | P_{i:02d} | {i * 1.25:.2f} | dB |")
        rows.append("| Maximum Excursion | Xmax | 5.65 | mm |")
        table_doc = "\n".join(rows)
        query_tbl = "Maximum Excursion Xmax table value"
        actual_tbl = self.docintel.process(table_doc, query_tbl, url="https://specs.example.com/table")
        expected_tbl = _legacy_docintel_process(table_doc, query_tbl)

        self.assertEqual(actual_tbl, expected_tbl)
        self.assertIn("| Maximum Excursion | Xmax | 5.65 | mm |", actual_tbl["formatted"])

    # ------------------------------------------------------------------
    # 5. DEEP TARGET EVIDENCE (Jauh di Dalam Dokumen)
    # ------------------------------------------------------------------
    def test_deep_target_in_long_structured_document(self):
        # 18 sections (~18,000 chars); target evidence is at section 16 (char > 15,000)
        sections = []
        for i in range(1, 16):
            filler = f"Filler paragraph for chapter {i} covering background operations and metrics. " * 18
            sections.append(f"## Chapter {i}: Background Operations\n{filler}")
        target_sec = (
            "## Chapter 16: Raft Snapshot Compaction Protocol\n"
            "When the Raft write-ahead log exceeds snapshot_threshold_entries=50000, "
            "the state machine serializes a deterministic checkpoint and truncates "
            "all preceding log indices up to last_applied_index."
        )
        sections.append(target_sec)
        for i in range(17, 19):
            filler = f"Appendix {i} notes on deployment topology and monitoring alerts. " * 15
            sections.append(f"## Chapter {i}: Appendix Notes\n{filler}")

        full_doc = "# Distributed Storage Engine Manual\n\n" + "\n\n".join(sections)
        self.assertGreater(full_doc.find("snapshot_threshold_entries=50000"), 15000)

        query = "Raft snapshot compaction protocol snapshot_threshold_entries last_applied_index"
        actual = self.docintel.process(full_doc, query, url="https://docs.example.com/storage/manual")
        expected = _legacy_docintel_process(full_doc, query)

        self.assertEqual(actual["doc_type"], "documentation")
        self.assertEqual(actual, expected)
        self.assertIn("snapshot_threshold_entries=50000", actual["formatted"])
        self.assertLess(actual["formatted"].find("snapshot_threshold_entries=50000"), 500)
        self.assertIn("snapshot_threshold_entries=50000", actual["formatted"][:5000])

    def test_deep_target_in_real_searcher_py_source_code(self):
        searcher_path = os.path.join(REPO_ROOT, "aran_search", "searcher.py")
        with open(searcher_path, "r", encoding="utf-8") as f:
            raw_searcher = f.read()

        self.assertGreater(len(raw_searcher), 35000)
        self.assertGreater(raw_searcher.find("def fetch_url"), 20000)

        query = (
            "Extract the implementation details of the fetch_url() function in "
            "aran_search/searcher.py and explain how GitHub URLs are processed."
        )
        res = self.docintel.process(
            raw_searcher,
            query,
            url="https://github.com/afikafera/12.kirim-baru/blob/master/aran_search/searcher.py",
        )
        self.assertEqual(res["doc_type"], "source_code")
        self.assertNotIn("## Specifications", res["formatted"])
        self.assertLess(len(res["formatted"]), 5000)
        self.assertIn("def fetch_url(self, url: str) -> str:", res["formatted"])
        self.assertIn("Connectors > yt-dlp > Jina > Browser", res["formatted"])
        self.assertIn("_github_contents_api_url", res["formatted"])
        self.assertIn('if "github.com" in url:', res["formatted"])
        self.assertIn("base64.b64decode", res["formatted"])

    @staticmethod
    def _long_jina_python_source():
        blocks = ["import os", "import json"]
        for index in range(180):
            blocks.append(
                f"def filler_function_{index}(value):\n"
                f"    intermediate_value_{index} = value + {index}\n"
                f"    return intermediate_value_{index}"
            )
        blocks.append(
            "def deep_jina_sentinel(payload):\n"
            "    deep_jina_sentinel_value = payload.strip()\n"
            "    return deep_jina_sentinel_value"
        )
        return "\n\n".join(blocks) + "\n"

    def _fetch_mocked_jina_source(self):
        source = self._long_jina_python_source()
        completed = subprocess.CompletedProcess(
            args=["curl"],
            returncode=0,
            stdout=source + "\n__FETCH_HTTP_STATUS__:200\n",
            stderr="",
        )
        with patch("aran_search.searcher.subprocess.run", return_value=completed):
            fetched = AgentReachSearcher().fetch_url(
                "https://example.org/public/long_source.py"
            )
        return source, fetched

    def test_successful_jina_response_preserves_content_beyond_8000(self):
        source, fetched = self._fetch_mocked_jina_source()
        self.assertGreater(len(source), 8000)
        self.assertGreater(source.find("deep_jina_sentinel"), 8000)
        self.assertGreater(len(fetched), 8000)
        self.assertIn("deep_jina_sentinel", fetched)

    def test_deep_jina_sentinel_survives_fetch_and_docintel(self):
        _, fetched = self._fetch_mocked_jina_source()
        result = self.docintel.process(
            fetched,
            "deep_jina_sentinel deep_jina_sentinel_value",
            url="https://example.org/public/long_source.py",
        )
        self.assertEqual(result["char_before"], len(fetched))
        self.assertEqual(result["doc_type"], "source_code")
        self.assertIn("deep_jina_sentinel", result["formatted"])
        self.assertIn("deep_jina_sentinel_value", result["formatted"])

    def test_giant_function_without_blank_lines_is_split_to_cap(self):
        lines = ["def giant_dense_function(value):"]
        lines.extend(f"    dense_value_{i} = value + {i}" for i in range(260))
        lines.append("    deep_dense_sentinel = dense_value_259")
        lines.append("    return deep_dense_sentinel")
        sections = SectionEngine().split_sections(
            "\n".join(lines), doc_type="source_code"
        )
        self.assertGreater(len(sections), 1)
        self.assertTrue(all(len(section["text"]) <= 1000 for section in sections))
        self.assertEqual(
            [section["part_index"] for section in sections],
            list(range(1, len(sections) + 1)),
        )
        self.assertTrue(
            all(section["part_total"] == len(sections) for section in sections)
        )
        formatted = SectionEngine().rank_and_filter(
            sections, "deep_dense_sentinel", doc_type="source_code"
        )
        self.assertIn("deep_dense_sentinel", formatted)

    def test_single_source_line_over_cap_is_hard_split(self):
        source = (
            "import os\n"
            "def giant_single_line():\n"
            "    payload = '" + ("x" * 1350) + "deep_single_line_sentinel'\n"
            "    return payload\n"
        )
        sections = SectionEngine().split_sections(source, doc_type="source_code")
        self.assertGreater(len(sections), 1)
        self.assertTrue(all(len(section["text"]) <= 1000 for section in sections))
        self.assertIn(
            "deep_single_line_sentinel",
            "".join(section["text"] for section in sections),
        )
        formatted = SectionEngine().rank_and_filter(
            sections, "deep_single_line_sentinel", doc_type="source_code"
        )
        self.assertIn("deep_single_line_sentinel", formatted)

    def test_first_middle_and_last_source_targets_remain_discoverable(self):
        lines = [
            "def positional_targets(value):",
            "    first_position_sentinel = value",
        ]
        lines.extend(f"    prefix_value_{i} = value + {i}" for i in range(100))
        lines.append("    middle_position_sentinel = prefix_value_99")
        lines.extend(f"    suffix_value_{i} = value + {i}" for i in range(100))
        lines.extend([
            "    last_position_sentinel = suffix_value_99",
            "    return last_position_sentinel",
        ])
        sections = SectionEngine().split_sections(
            "\n".join(lines), doc_type="source_code"
        )
        for target in (
            "first_position_sentinel",
            "middle_position_sentinel",
            "last_position_sentinel",
        ):
            with self.subTest(target=target):
                formatted = SectionEngine().rank_and_filter(
                    sections, target, doc_type="source_code"
                )
                self.assertIn(target, formatted)

    def test_source_chunk_order_and_parent_metadata_are_preserved(self):
        source = (
            "def alpha_function():\n"
            "    alpha_order_sentinel = 1\n"
            "    return alpha_order_sentinel\n\n"
            "def dense_middle_function():\n"
            + "\n".join(f"    middle_order_{i} = {i}" for i in range(180))
            + "\n    return middle_order_179\n\n"
            "def omega_function():\n"
            "    omega_order_sentinel = 3\n"
            "    return omega_order_sentinel\n"
        )
        sections = SectionEngine().split_sections(source, doc_type="source_code")
        joined = "\n".join(section["text"] for section in sections)
        self.assertLess(
            joined.find("alpha_order_sentinel"), joined.find("middle_order_90")
        )
        self.assertLess(
            joined.find("middle_order_90"), joined.find("omega_order_sentinel")
        )
        middle = [
            section for section in sections
            if section["parent_heading"].startswith("def dense_middle_function")
        ]
        self.assertGreater(len(middle), 1)
        self.assertEqual(
            [section["part_index"] for section in middle],
            list(range(1, len(middle) + 1)),
        )
        self.assertTrue(
            all(section["part_total"] == len(middle) for section in middle)
        )

    def test_source_extension_does_not_override_rendered_markdown_shape(self):
        rendered = (
            "# Repository file preview\n"
            "The requested file could not be rendered.\n"
            "[Repository](https://example.org/repo)\n"
            "[Sign in](https://example.org/login)\n"
            "[Help](https://example.org/help)\n"
        )
        self.assertNotEqual(
            Classifier().classify(rendered, url="https://example.org/error.py"),
            "source_code",
        )

    def test_source_extension_preserves_real_python_detection(self):
        source = (
            "import os\n"
            "from pathlib import Path\n\n"
            "def load_configuration(path):\n"
            "    return Path(path).read_text()\n\n"
            "def main():\n"
            "    return load_configuration(os.environ['APP_CONFIG'])\n"
        )
        self.assertEqual(
            Classifier().classify(source, url="https://example.org/config.py"),
            "source_code",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

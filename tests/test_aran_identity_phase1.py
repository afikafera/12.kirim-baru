import ast
import importlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AranIdentityPhase1Tests(unittest.TestCase):
    def test_package_exports_primary_and_legacy_class_as_same_object(self):
        from hermes_agent import AranAgent, HermesAgent

        self.assertIs(AranAgent, HermesAgent)

    def test_api_imports_and_constructs_aran_agent(self):
        source = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        imports_aran = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "hermes_agent.orchestrator"
            and any(alias.name == "AranAgent" for alias in node.names)
            for node in ast.walk(module)
        )
        constructs_aran = any(
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "aran" for target in node.targets)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "AranAgent"
            for node in ast.walk(module)
        )
        self.assertTrue(imports_aran, "api.main must import AranAgent")
        self.assertTrue(constructs_aran, "api.main must construct AranAgent")

    def test_api_chat_route_and_research_metadata_contract_remain(self):
        source = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
        self.assertIn('"/chat/completions"', source)
        self.assertIn("ensure_research_metadata(result)", source)
        self.assertIn('"finish_reason": "stop"', source)

    def test_trace_name_uses_aran_identity(self):
        source = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
        self.assertIn('name="aran-research"', source)

    def test_jsonl_logger_default_path_uses_aran_identity(self):
        logger = importlib.import_module("hermes_agent.jsonl_logger")
        self.assertEqual(logger._LOG, Path("/tmp/aran_events.jsonl"))

    def test_active_archify_converter_uses_aran_identity(self):
        source = (ROOT / "archify" / "tools" / "hermes_trace_to_workflow.py").read_text(encoding="utf-8")
        self.assertIn("ARAN Core", source)
        self.assertIn("ARAN Trace {request_id}", source)

    def test_archify_reader_prefers_new_telemetry_path(self):
        reader = importlib.import_module("archify.tools.hermes_archify_live")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            new_path = root / "aran_events.jsonl"
            old_path = root / "hermes_events.jsonl"
            new_path.write_text('{"request_id":"new","event":"new"}\n', encoding="utf-8")
            old_path.write_text('{"request_id":"old","event":"old"}\n', encoding="utf-8")
            with patch.object(reader, "TRACE", new_path), patch.object(reader, "LEGACY_TRACE", old_path, create=True):
                events = reader.read_events()
        self.assertEqual([event["request_id"] for event in events], ["new"])

    def test_archify_reader_falls_back_to_legacy_telemetry_path(self):
        reader = importlib.import_module("archify.tools.hermes_archify_live")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            new_path = root / "aran_events.jsonl"
            old_path = root / "hermes_events.jsonl"
            old_path.write_text('{"request_id":"legacy","event":"old"}\n', encoding="utf-8")
            with patch.object(reader, "TRACE", new_path), patch.object(reader, "LEGACY_TRACE", old_path, create=True):
                events = reader.read_events()
        self.assertEqual([event["request_id"] for event in events], ["legacy"])


if __name__ == "__main__":
    unittest.main()

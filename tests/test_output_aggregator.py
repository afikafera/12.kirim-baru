import copy
import unittest

from hermes_agent.output_aggregator import (
    AggregatedOutput,
    OutputAggregator,
)
from hermes_agent.output_manifest import (
    OutputManifest,
    OutputSection,
    ScalerStatus,
    SectionRuntimeState,
    SectionStatus,
)
from hermes_agent.section_store import SectionStore


def build_manifest(*section_ids):
    sections = [
        OutputSection(
            section_id=section_id,
            requirement_id=f"REQ-{section_id}",
            title=f"Title {section_id}",
            intent=f"Intent {section_id}",
            must_cover=[f"cover-{section_id}"],
        )
        for section_id in section_ids
    ]

    return OutputManifest(
        manifest_id="test-manifest",
        version=1,
        goal="test goal",
        sections=sections,
        global_acceptance=[],
        constraints=[],
        order_policy="manifest_order",
    )


def put_state(
    store,
    section_id,
    status,
    text="",
    tokens=0,
):
    state = SectionRuntimeState(
        section_id=section_id,
        status=status,
        accumulated_text=text,
        budget_used_tokens=tokens,
    )
    store.put(state)


class OutputAggregatorTests(unittest.TestCase):

    def test_manifest_order_is_preserved(self):
        manifest = build_manifest("S001", "S002", "S003")
        store = SectionStore()

        # Insert deliberately in a different order.
        put_state(
            store,
            "S003",
            SectionStatus.STORED_FINAL,
            "third",
            30,
        )
        put_state(
            store,
            "S001",
            SectionStatus.STORED_FINAL,
            "first",
            10,
        )
        put_state(
            store,
            "S002",
            SectionStatus.STORED_FINAL,
            "second",
            20,
        )

        result = OutputAggregator().aggregate(manifest, store)

        self.assertEqual(
            result.content,
            "first\n\nsecond\n\nthird",
        )
        self.assertEqual(result.scaler_status, ScalerStatus.DONE)

    def test_mixed_final_degraded_failed(self):
        manifest = build_manifest("S001", "S002", "S003")
        store = SectionStore()

        put_state(
            store,
            "S001",
            SectionStatus.STORED_FINAL,
            "final section",
            10,
        )
        put_state(
            store,
            "S002",
            SectionStatus.DEGRADED,
            "partial section",
            20,
        )
        put_state(
            store,
            "S003",
            SectionStatus.FAILED,
            "",
            30,
        )

        result = OutputAggregator().aggregate(manifest, store)

        self.assertEqual(
            result.content,
            "final section\n\npartial section\n\n"
            "[Section gagal diproduksi: Title S003]",
        )
        self.assertEqual(result.sections_total, 3)
        self.assertEqual(result.sections_final, 1)
        self.assertEqual(result.sections_degraded, 1)
        self.assertEqual(result.sections_failed, 1)
        self.assertEqual(result.total_tokens_used, 60)
        self.assertEqual(result.scaler_status, ScalerStatus.PARTIAL)

    def test_empty_non_failed_sections_do_not_create_blank_output(self):
        manifest = build_manifest("S001", "S002", "S003")
        store = SectionStore()

        put_state(
            store,
            "S001",
            SectionStatus.STORED_FINAL,
            "  first  ",
        )
        put_state(
            store,
            "S002",
            SectionStatus.STORED_FINAL,
            "   ",
        )
        put_state(
            store,
            "S003",
            SectionStatus.STORED_FINAL,
            "\n second\n\n",
        )

        result = OutputAggregator().aggregate(manifest, store)

        self.assertEqual(result.content, "first\n\nsecond")
        self.assertEqual(result.scaler_status, ScalerStatus.DONE)

    def test_all_failed_produces_failed_status(self):
        manifest = build_manifest("S001", "S002")
        store = SectionStore()

        put_state(store, "S001", SectionStatus.FAILED, "", 5)
        put_state(store, "S002", SectionStatus.FAILED, "", 7)

        result = OutputAggregator().aggregate(manifest, store)

        self.assertEqual(result.sections_total, 2)
        self.assertEqual(result.sections_final, 0)
        self.assertEqual(result.sections_degraded, 0)
        self.assertEqual(result.sections_failed, 2)
        self.assertEqual(result.total_tokens_used, 12)
        self.assertEqual(result.scaler_status, ScalerStatus.FAILED)
        self.assertIn("Title S001", result.content)
        self.assertIn("Title S002", result.content)

    def test_all_final_is_done(self):
        manifest = build_manifest("S001", "S002")
        store = SectionStore()

        put_state(
            store,
            "S001",
            SectionStatus.STORED_FINAL,
            "one",
            11,
        )
        put_state(
            store,
            "S002",
            SectionStatus.STORED_FINAL,
            "two",
            13,
        )

        result = OutputAggregator().aggregate(manifest, store)

        self.assertEqual(result.scaler_status, ScalerStatus.DONE)
        self.assertEqual(result.total_tokens_used, 24)

    def test_degraded_without_final_is_partial(self):
        manifest = build_manifest("S001", "S002")
        store = SectionStore()

        put_state(
            store,
            "S001",
            SectionStatus.DEGRADED,
            "partial one",
        )
        put_state(
            store,
            "S002",
            SectionStatus.DEGRADED,
            "partial two",
        )

        result = OutputAggregator().aggregate(manifest, store)

        self.assertEqual(result.sections_final, 0)
        self.assertEqual(result.sections_degraded, 2)
        self.assertEqual(result.sections_failed, 0)
        self.assertEqual(result.scaler_status, ScalerStatus.PARTIAL)

    def test_empty_manifest_is_failed(self):
        manifest = build_manifest()
        store = SectionStore()

        result = OutputAggregator().aggregate(manifest, store)

        self.assertEqual(result.content, "")
        self.assertEqual(result.sections_total, 0)
        self.assertEqual(result.scaler_status, ScalerStatus.FAILED)

    def test_store_is_not_mutated(self):
        manifest = build_manifest("S001", "S002")
        store = SectionStore()

        put_state(
            store,
            "S001",
            SectionStatus.STORED_FINAL,
            "first",
            10,
        )
        put_state(
            store,
            "S002",
            SectionStatus.DEGRADED,
            "second",
            20,
        )

        before = copy.deepcopy(store.all())

        OutputAggregator().aggregate(manifest, store)

        after = store.all()

        self.assertEqual(before, after)

    def test_include_headers_is_deterministic(self):
        manifest = build_manifest("S001", "S002")
        store = SectionStore()

        put_state(
            store,
            "S001",
            SectionStatus.STORED_FINAL,
            "one",
        )
        put_state(
            store,
            "S002",
            SectionStatus.STORED_FINAL,
            "two",
        )

        result = OutputAggregator(
            include_headers=True,
        ).aggregate(manifest, store)

        self.assertEqual(
            result.content,
            "## Title S001\n\none\n\n"
            "## Title S002\n\ntwo",
        )

    def test_invalid_manifest_type_is_rejected(self):
        store = SectionStore()

        with self.assertRaises(TypeError):
            OutputAggregator().aggregate({}, store)

    def test_invalid_store_type_is_rejected(self):
        manifest = build_manifest("S001")

        with self.assertRaises(TypeError):
            OutputAggregator().aggregate(manifest, {})


if __name__ == "__main__":
    unittest.main()

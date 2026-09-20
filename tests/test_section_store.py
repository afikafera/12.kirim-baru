import unittest

from hermes_agent.output_manifest import (
    OutcomeType,
    SectionRuntimeState,
    SectionStatus,
)
from hermes_agent.section_store import SectionStore


class TestSectionStore(unittest.TestCase):

    def test_create_and_get(self):
        store = SectionStore()

        state = store.create("S001")

        self.assertEqual(state.section_id, "S001")
        self.assertEqual(state.status, SectionStatus.PENDING)
        self.assertTrue(store.exists("S001"))
        self.assertEqual(store.get("S001").section_id, "S001")

    def test_duplicate_create_rejected(self):
        store = SectionStore()
        store.create("S001")

        with self.assertRaisesRegex(ValueError, "already exists"):
            store.create("S001")

    def test_put_replaces_state(self):
        store = SectionStore()

        state = SectionRuntimeState(
            section_id="S001",
            status=SectionStatus.STORED_FINAL,
            accumulated_text="complete",
        )

        store.put(state)

        restored = store.get("S001")

        self.assertEqual(restored.status, SectionStatus.STORED_FINAL)
        self.assertEqual(restored.accumulated_text, "complete")

    def test_get_returns_defensive_copy(self):
        store = SectionStore()
        store.create("S001")

        state = store.get("S001")
        state.chunks.append("mutated externally")

        stored = store.get("S001")

        self.assertEqual(stored.chunks, [])

    def test_append_chunk_preserves_order(self):
        store = SectionStore()
        store.create("S001")

        store.append_chunk("S001", "Hello ")
        store.append_chunk("S001", "world.")

        state = store.get("S001")

        self.assertEqual(
            state.chunks,
            ["Hello ", "world."],
        )
        self.assertEqual(
            state.accumulated_text,
            "Hello world.",
        )

    def test_metadata_update(self):
        store = SectionStore()
        store.create("S001")

        state = store.update_metadata(
            "S001",
            attempts_total=2,
            continuation_count=1,
            budget_used_tokens=1200,
            last_model="model-a",
            last_finish_reason="length",
            last_tokens_output=1024,
            last_outcome=OutcomeType.TRUNCATED,
        )

        self.assertEqual(state.attempts_total, 2)
        self.assertEqual(state.continuation_count, 1)
        self.assertEqual(state.budget_used_tokens, 1200)
        self.assertEqual(state.last_model, "model-a")
        self.assertEqual(state.last_finish_reason, "length")
        self.assertEqual(state.last_tokens_output, 1024)
        self.assertEqual(state.last_outcome, OutcomeType.TRUNCATED)

    def test_all_is_deterministic(self):
        store = SectionStore()

        store.create("S003")
        store.create("S001")
        store.create("S002")

        self.assertEqual(
            [s.section_id for s in store.all()],
            ["S001", "S002", "S003"],
        )

    def test_unknown_section_rejected(self):
        store = SectionStore()

        with self.assertRaises(KeyError):
            store.get("S999")

        with self.assertRaises(KeyError):
            store.delete("S999")

        with self.assertRaises(KeyError):
            store.append_chunk("S999", "text")

    def test_invalid_state_type_rejected(self):
        store = SectionStore()

        with self.assertRaises(TypeError):
            store.put({"section_id": "S001"})

    def test_empty_chunk_rejected(self):
        store = SectionStore()
        store.create("S001")

        with self.assertRaises(ValueError):
            store.append_chunk("S001", "")

    def test_delete(self):
        store = SectionStore()
        store.create("S001")

        store.delete("S001")

        self.assertFalse(store.exists("S001"))

        with self.assertRaises(KeyError):
            store.get("S001")


if __name__ == "__main__":
    unittest.main()

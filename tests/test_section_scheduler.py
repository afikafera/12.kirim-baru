import unittest

from hermes_agent.output_manifest import (
    OutputManifest,
    OutputSection,
    SectionStatus,
)
from hermes_agent.section_scheduler import SectionScheduler


def make_manifest(sections):
    return OutputManifest(
        manifest_id="test-manifest",
        version="1.0",
        goal="test",
        sections=sections,
    )


class TestSectionScheduler(unittest.TestCase):

    def test_initial_ready_sections_are_deterministic(self):
        manifest = make_manifest([
            OutputSection("S001", "R1", "One", "one", []),
            OutputSection("S002", "R2", "Two", "two", []),
            OutputSection("S003", "R3", "Three", "three", [], ["S001"]),
        ])

        scheduler = SectionScheduler(manifest)
        scheduler.initialize()

        self.assertEqual(
            [s.section_id for s in scheduler.ready_sections()],
            ["S001", "S002"],
        )

    def test_dependency_unlocks_after_completion(self):
        manifest = make_manifest([
            OutputSection("S001", "R1", "One", "one", []),
            OutputSection("S002", "R2", "Two", "two", [], ["S001"]),
        ])

        scheduler = SectionScheduler(manifest)
        scheduler.initialize()

        self.assertEqual(
            [s.section_id for s in scheduler.ready_sections()],
            ["S001"],
        )

        scheduler.mark_in_flight("S001")
        scheduler.mark_complete("S001")

        self.assertEqual(
            [s.section_id for s in scheduler.ready_sections()],
            ["S002"],
        )

    def test_multiple_dependencies_require_all(self):
        manifest = make_manifest([
            OutputSection("S001", "R1", "One", "one", []),
            OutputSection("S002", "R2", "Two", "two", []),
            OutputSection(
                "S003", "R3", "Three", "three", [], ["S001", "S002"]
            ),
        ])

        scheduler = SectionScheduler(manifest)
        scheduler.initialize()

        scheduler.mark_in_flight("S001")
        scheduler.mark_complete("S001")

        self.assertEqual(scheduler.ready_sections(), [
            manifest.sections[1]
        ])

        scheduler.mark_in_flight("S002")
        scheduler.mark_complete("S002")

        self.assertEqual(
            [s.section_id for s in scheduler.ready_sections()],
            ["S003"],
        )

    def test_failed_dependency_does_not_unlock_child(self):
        manifest = make_manifest([
            OutputSection("S001", "R1", "One", "one", []),
            OutputSection("S002", "R2", "Two", "two", [], ["S001"]),
        ])

        scheduler = SectionScheduler(manifest)
        scheduler.initialize()

        scheduler.mark_in_flight("S001")
        scheduler.mark_failed("S001")

        self.assertEqual(scheduler.ready_sections(), [])

    def test_degraded_dependency_does_not_unlock_child(self):
        manifest = make_manifest([
            OutputSection("S001", "R1", "One", "one", []),
            OutputSection("S002", "R2", "Two", "two", [], ["S001"]),
        ])

        scheduler = SectionScheduler(manifest)
        scheduler.initialize()

        scheduler.mark_in_flight("S001")
        scheduler.mark_degraded("S001")

        self.assertEqual(scheduler.ready_sections(), [])

    def test_unknown_dependency_rejected(self):
        manifest = make_manifest([
            OutputSection(
                "S001", "R1", "One", "one", [], ["S999"]
            ),
        ])

        with self.assertRaisesRegex(ValueError, "unknown dependency"):
            SectionScheduler(manifest)

    def test_cycle_rejected(self):
        manifest = make_manifest([
            OutputSection("S001", "R1", "One", "one", [], ["S002"]),
            OutputSection("S002", "R2", "Two", "two", [], ["S001"]),
        ])

        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            SectionScheduler(manifest)

    def test_duplicate_section_rejected(self):
        manifest = make_manifest([
            OutputSection("S001", "R1", "One", "one", []),
            OutputSection("S001", "R2", "Duplicate", "duplicate", []),
        ])

        with self.assertRaisesRegex(ValueError, "duplicate section_id"):
            SectionScheduler(manifest)

    def test_invalid_transition_rejected(self):
        manifest = make_manifest([
            OutputSection("S001", "R1", "One", "one", []),
        ])

        scheduler = SectionScheduler(manifest)
        scheduler.initialize()

        with self.assertRaises(ValueError):
            scheduler.mark_complete("S001")

        with self.assertRaises(ValueError):
            scheduler.mark_failed("S001")


if __name__ == "__main__":
    unittest.main()

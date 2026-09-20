import unittest

from hermes_agent.output_manifest import OutputSection, SectionStatus
from hermes_agent.section_splitter import SectionSplitter


class TestSectionSplitter(unittest.TestCase):

    def make_section(self, must_cover):
        return OutputSection(
            section_id="S002",
            requirement_id="R002",
            title="Implementation",
            intent="Explain implementation",
            must_cover=list(must_cover),
            depends_on=[],
        )

    def test_single_remaining_item_creates_one_child(self):
        splitter = SectionSplitter()

        children = splitter.partition(
            self.make_section(["redis_configuration"]),
            ["redis_configuration"],
        )

        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].parent_section_id, "S002")
        self.assertEqual(children[0].child_section_id, "S002_c1")
        self.assertEqual(
            children[0].section.must_cover,
            ["redis_configuration"],
        )

    def test_multiple_remaining_items_create_deterministic_children(self):
        splitter = SectionSplitter()

        children = splitter.partition(
            self.make_section(
                [
                    "redis_configuration",
                    "uwsgi_setup",
                    "deployment",
                ]
            ),
            ["uwsgi_setup", "redis_configuration"],
        )

        self.assertEqual(
            [child.child_section_id for child in children],
            ["S002_c1", "S002_c2"],
        )

        self.assertEqual(
            [child.section.must_cover for child in children],
            [
                ["redis_configuration"],
                ["uwsgi_setup"],
            ],
        )

    def test_partition_ignores_unknown_remaining_items(self):
        splitter = SectionSplitter()

        children = splitter.partition(
            self.make_section(["redis_configuration"]),
            ["unknown_item"],
        )

        self.assertEqual(children, [])

    def test_reconcile_accumulates_child_text_and_tokens(self):
        splitter = SectionSplitter()

        result = splitter.reconcile(
            parent_section_id="S002",
            child_results=[
                {
                    "child_section_id": "S002_c1",
                    "content": "Redis.",
                    "covered_items": ["redis_configuration"],
                    "tokens_output": 50,
                },
                {
                    "child_section_id": "S002_c2",
                    "content": "uWSGI.",
                    "covered_items": ["uwsgi_setup"],
                    "tokens_output": 70,
                },
            ],
            remaining_items=[],
        )

        self.assertEqual(
            result["accumulated_text"],
            "Redis.\nuWSGI.",
        )
        self.assertEqual(result["tokens_output"], 120)
        self.assertEqual(
            result["covered_items"],
            [
                "redis_configuration",
                "uwsgi_setup",
            ],
        )
        self.assertEqual(result["remaining_items"], [])

    def test_failed_child_does_not_count_as_coverage(self):
        splitter = SectionSplitter()

        result = splitter.reconcile(
            parent_section_id="S002",
            child_results=[
                {
                    "child_section_id": "S002_c1",
                    "content": "",
                    "covered_items": [],
                    "tokens_output": 0,
                    "status": SectionStatus.FAILED,
                }
            ],
            remaining_items=["redis_configuration"],
        )

        self.assertEqual(result["covered_items"], [])
        self.assertEqual(
            result["remaining_items"],
            ["redis_configuration"],
        )

    def test_degraded_child_does_not_count_as_coverage(self):
        splitter = SectionSplitter()

        result = splitter.reconcile(
            parent_section_id="S002",
            child_results=[
                {
                    "child_section_id": "S002_c1",
                    "content": "Incomplete.",
                    "covered_items": ["redis_configuration"],
                    "tokens_output": 20,
                    "status": SectionStatus.DEGRADED,
                }
            ],
            remaining_items=["redis_configuration"],
        )

        self.assertEqual(result["covered_items"], [])
        self.assertEqual(
            result["remaining_items"],
            ["redis_configuration"],
        )


if __name__ == "__main__":
    unittest.main()

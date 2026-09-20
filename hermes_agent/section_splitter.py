"""
Deterministic in-section splitting and reconciliation for Output Scaling.

Child sections are execution units only.

They are deliberately NOT added to:
- OutputManifest
- SectionScheduler

Their results are reconciled back into the parent section runtime state.
"""

from dataclasses import dataclass
from typing import Any

from hermes_agent.output_manifest import OutputSection, SectionStatus


@dataclass(frozen=True)
class SplitChild:
    """One deterministic child execution unit."""

    parent_section_id: str
    child_section_id: str
    section: OutputSection


class SectionSplitter:
    """Partition remaining coverage items into child sections."""

    def partition(
        self,
        section: OutputSection,
        remaining_items: list[str],
    ) -> list[SplitChild]:
        """
        Create one child per valid remaining coverage item.

        Ordering is deterministic according to section.must_cover.
        Unknown remaining items are ignored.
        """

        remaining = set(remaining_items)
        children: list[SplitChild] = []

        child_index = 0

        for item in section.must_cover:
            if item not in remaining:
                continue

            child_index += 1
            child_section_id = (
                f"{section.section_id}_c{child_index}"
            )

            child = OutputSection(
                section_id=child_section_id,
                requirement_id=section.requirement_id,
                title=section.title,
                intent=section.intent,
                must_cover=[item],
                depends_on=[],
                expected_shape=section.expected_shape,
                priority=section.priority,
                budget_hint=section.budget_hint,
                max_continuations=section.max_continuations,
            )

            children.append(
                SplitChild(
                    parent_section_id=section.section_id,
                    child_section_id=child_section_id,
                    section=child,
                )
            )

        return children

    def reconcile(
        self,
        parent_section_id: str,
        child_results: list[dict[str, Any]],
        remaining_items: list[str],
    ) -> dict[str, Any]:
        """
        Reconcile successful child output.

        Failed/degraded children do not contribute coverage.

        Semantic completeness is NOT calculated here.
        CoverageEvaluator remains the owner of semantic completeness.
        """

        parts: list[str] = []
        covered_items: list[str] = []
        tokens_output = 0

        for result in child_results:
            status = result.get("status")

            if status in (
                SectionStatus.FAILED,
                SectionStatus.DEGRADED,
            ):
                continue

            content = result.get("content", "")

            if isinstance(content, str) and content.strip():
                parts.append(content.strip())

            for item in result.get("covered_items", []):
                if item not in covered_items:
                    covered_items.append(item)

            tokens_output += int(
                result.get("tokens_output", 0) or 0
            )

        return {
            "parent_section_id": parent_section_id,
            "accumulated_text": "\n".join(parts),
            "tokens_output": tokens_output,
            "covered_items": covered_items,
            "remaining_items": list(remaining_items),
        }

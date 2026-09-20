"""
Deterministic output aggregation for Hermes Output Scaling.

Boundary:
    OutputManifest + SectionStore -> AggregatedOutput

The aggregator does not execute, route, retry, validate, or mutate.
"""

from dataclasses import dataclass
from typing import List

from hermes_agent.output_manifest import (
    OutputManifest,
    SectionStatus,
    ScalerStatus,
)
from hermes_agent.section_store import SectionStore


@dataclass(frozen=True)
class AggregatedOutput:
    """Immutable result of deterministic section aggregation."""

    content: str
    sections_total: int
    sections_final: int
    sections_degraded: int
    sections_failed: int
    total_tokens_used: int
    scaler_status: ScalerStatus


class OutputAggregator:
    """
    Deterministically combine section outputs in manifest order.

    This component deliberately has no LLM, network, external IO,
    routing, retry, semantic evaluation, or store mutation.
    """

    def __init__(
        self,
        separator: str = "\n\n",
        include_headers: bool = False,
    ):
        if not isinstance(separator, str):
            raise TypeError("separator must be a string")

        self.separator = separator
        self.include_headers = bool(include_headers)

    def aggregate(
        self,
        manifest: OutputManifest,
        store: SectionStore,
    ) -> AggregatedOutput:
        if not isinstance(manifest, OutputManifest):
            raise TypeError("manifest must be OutputManifest")

        if not isinstance(store, SectionStore):
            raise TypeError("store must be SectionStore")

        states = []
        for section in manifest.sections:
            states.append(store.get(section.section_id))

        sections_total = len(states)
        sections_final = sum(
            1
            for state in states
            if state.status == SectionStatus.STORED_FINAL
        )
        sections_degraded = sum(
            1
            for state in states
            if state.status == SectionStatus.DEGRADED
        )
        sections_failed = sum(
            1
            for state in states
            if state.status == SectionStatus.FAILED
        )

        total_tokens_used = sum(
            int(state.budget_used_tokens or 0)
            for state in states
        )

        parts: List[str] = []

        for section, state in zip(manifest.sections, states):
            text = self._normalize_text(state.accumulated_text)

            if not text:
                if state.status == SectionStatus.FAILED:
                    text = self._failure_placeholder(section)
                else:
                    continue

            if self.include_headers:
                text = f"## {section.title}\n\n{text}"

            parts.append(text)

        content = self.separator.join(parts)

        if sections_total == 0:
            scaler_status = ScalerStatus.FAILED
        elif sections_final == sections_total:
            scaler_status = ScalerStatus.DONE
        elif sections_final > 0 or sections_degraded > 0:
            scaler_status = ScalerStatus.PARTIAL
        else:
            scaler_status = ScalerStatus.FAILED

        return AggregatedOutput(
            content=content,
            sections_total=sections_total,
            sections_final=sections_final,
            sections_degraded=sections_degraded,
            sections_failed=sections_failed,
            total_tokens_used=total_tokens_used,
            scaler_status=scaler_status,
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        if text is None:
            return ""

        if not isinstance(text, str):
            raise TypeError("accumulated_text must be a string")

        return text.strip()

    @staticmethod
    def _failure_placeholder(section) -> str:
        title = str(section.title).strip() or section.section_id
        return (
            f"[Section gagal diproduksi: {title}]"
        )

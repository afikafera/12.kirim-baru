"""
Deterministic scheduler for Hermes Output Scaling sections.

The scheduler owns section readiness and lifecycle transitions only.
It does not execute LLM calls, select providers, assemble output,
or perform semantic validation.
"""

from typing import Dict, List

from hermes_agent.output_manifest import (
    OutputManifest,
    OutputSection,
    SectionRuntimeState,
    SectionStatus,
)


class SectionScheduler:
    """Manage deterministic section readiness from an OutputManifest."""

    _TERMINAL_SUCCESS = SectionStatus.STORED_FINAL

    def __init__(self, manifest: OutputManifest):
        self.manifest = manifest
        self._sections: Dict[str, OutputSection] = {}
        self._states: Dict[str, SectionRuntimeState] = {}

        for section in manifest.sections:
            if section.section_id in self._sections:
                raise ValueError(
                    f"duplicate section_id: {section.section_id}"
                )
            self._sections[section.section_id] = section
            self._states[section.section_id] = SectionRuntimeState(
                section_id=section.section_id
            )

        self._validate_dependencies()
        self._validate_acyclic()

    def _validate_dependencies(self) -> None:
        """Reject dependencies that reference unknown sections."""
        known = set(self._sections)

        for section in self.manifest.sections:
            for dependency in section.depends_on:
                if dependency not in known:
                    raise ValueError(
                        f"unknown dependency: "
                        f"{section.section_id} depends_on {dependency}"
                    )

    def _validate_acyclic(self) -> None:
        """Reject dependency cycles deterministically."""
        visiting = set()
        visited = set()

        def visit(section_id: str) -> None:
            if section_id in visiting:
                raise ValueError(
                    f"dependency cycle detected at section: {section_id}"
                )
            if section_id in visited:
                return

            visiting.add(section_id)
            for dependency in self._sections[section_id].depends_on:
                visit(dependency)
            visiting.remove(section_id)
            visited.add(section_id)

        for section in self.manifest.sections:
            visit(section.section_id)

    def initialize(self) -> List[SectionRuntimeState]:
        """Move initially executable sections from PENDING to READY."""
        self._refresh_ready_states()
        return self.states()

    def _dependencies_met(self, section: OutputSection) -> bool:
        return all(
            self._states[dependency].status == self._TERMINAL_SUCCESS
            for dependency in section.depends_on
        )

    def _refresh_ready_states(self) -> None:
        """
        Promote eligible PENDING sections to READY.

        Manifest order is preserved for deterministic scheduling.
        """
        for section in self.manifest.sections:
            state = self._states[section.section_id]

            if state.status != SectionStatus.PENDING:
                continue

            if self._dependencies_met(section):
                state.status = SectionStatus.READY

    def ready_sections(self) -> List[OutputSection]:
        """Return currently READY sections in manifest order."""
        self._refresh_ready_states()

        return [
            section
            for section in self.manifest.sections
            if self._states[section.section_id].status == SectionStatus.READY
        ]

    def state(self, section_id: str) -> SectionRuntimeState:
        """Return the runtime state for one section."""
        self._require_section(section_id)
        return self._states[section_id]

    def states(self) -> List[SectionRuntimeState]:
        """Return all runtime states in manifest order."""
        return [
            self._states[section.section_id]
            for section in self.manifest.sections
        ]

    def mark_in_flight(self, section_id: str) -> None:
        """Transition READY -> IN_FLIGHT."""
        state = self._require_state(section_id)

        if state.status != SectionStatus.READY:
            raise ValueError(
                f"cannot mark {section_id} IN_FLIGHT from {state.status.value}"
            )

        state.status = SectionStatus.IN_FLIGHT

    def mark_complete(self, section_id: str) -> None:
        """Transition IN_FLIGHT -> STORED_FINAL."""
        state = self._require_state(section_id)

        if state.status != SectionStatus.IN_FLIGHT:
            raise ValueError(
                f"cannot mark {section_id} STORED_FINAL "
                f"from {state.status.value}"
            )

        state.status = SectionStatus.STORED_FINAL
        self._refresh_ready_states()

    def mark_degraded(self, section_id: str) -> None:
        """Transition IN_FLIGHT -> DEGRADED."""
        state = self._require_state(section_id)

        if state.status != SectionStatus.IN_FLIGHT:
            raise ValueError(
                f"cannot mark {section_id} DEGRADED from {state.status.value}"
            )

        state.status = SectionStatus.DEGRADED

    def mark_failed(self, section_id: str) -> None:
        """Transition IN_FLIGHT -> FAILED."""
        state = self._require_state(section_id)

        if state.status != SectionStatus.IN_FLIGHT:
            raise ValueError(
                f"cannot mark {section_id} FAILED from {state.status.value}"
            )

        state.status = SectionStatus.FAILED

    def _require_section(self, section_id: str) -> None:
        if section_id not in self._sections:
            raise KeyError(f"unknown section_id: {section_id}")

    def _require_state(self, section_id: str) -> SectionRuntimeState:
        self._require_section(section_id)
        return self._states[section_id]

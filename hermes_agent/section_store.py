"""
State store for Hermes Output Scaling sections.

This v1 implementation is intentionally in-memory. It provides an
explicit persistence boundary for SectionRuntimeState without coupling
Output Scaling to a database or filesystem.

The store does not execute, schedule, recover, validate, or assemble.
"""

from copy import deepcopy
from typing import Dict, List

from hermes_agent.output_manifest import SectionRuntimeState


class SectionStore:
    """Deterministic in-memory store for section runtime state."""

    def __init__(self):
        self._states: Dict[str, SectionRuntimeState] = {}

    def put(self, state: SectionRuntimeState) -> None:
        """Insert or replace a section state."""
        if not isinstance(state, SectionRuntimeState):
            raise TypeError("state must be SectionRuntimeState")

        section_id = str(state.section_id).strip()
        if not section_id:
            raise ValueError("section_id must not be empty")

        self._states[section_id] = deepcopy(state)

    def create(self, section_id: str) -> SectionRuntimeState:
        """Create and store a new PENDING section state."""
        section_id = str(section_id).strip()
        if not section_id:
            raise ValueError("section_id must not be empty")

        if section_id in self._states:
            raise ValueError(
                f"section already exists: {section_id}"
            )

        state = SectionRuntimeState(section_id=section_id)
        self._states[section_id] = deepcopy(state)
        return deepcopy(state)

    def get(self, section_id: str) -> SectionRuntimeState:
        """Return a defensive copy of one section state."""
        section_id = str(section_id).strip()

        if section_id not in self._states:
            raise KeyError(f"unknown section_id: {section_id}")

        return deepcopy(self._states[section_id])

    def exists(self, section_id: str) -> bool:
        """Return whether a section state exists."""
        return str(section_id).strip() in self._states

    def delete(self, section_id: str) -> None:
        """Delete one stored state."""
        section_id = str(section_id).strip()

        if section_id not in self._states:
            raise KeyError(f"unknown section_id: {section_id}")

        del self._states[section_id]

    def all(self) -> List[SectionRuntimeState]:
        """Return all states in deterministic section-id order."""
        return [
            deepcopy(self._states[section_id])
            for section_id in sorted(self._states)
        ]

    def append_chunk(self, section_id: str, chunk: str) -> SectionRuntimeState:
        """
        Append one non-empty text chunk and update accumulated_text.

        Chunk ordering is insertion ordering and therefore deterministic.
        """
        if not isinstance(chunk, str):
            raise TypeError("chunk must be a string")

        if not chunk:
            raise ValueError("chunk must not be empty")

        state = self.get(section_id)
        state.chunks.append(chunk)
        state.accumulated_text = "".join(state.chunks)
        self.put(state)

        return state

    def update_metadata(
        self,
        section_id: str,
        *,
        attempts_total=None,
        continuation_count=None,
        budget_used_tokens=None,
        last_model=None,
        last_finish_reason=None,
        last_tokens_output=None,
        last_outcome=None,
    ) -> SectionRuntimeState:
        """Update explicit runtime metadata without changing lifecycle state."""
        state = self.get(section_id)

        if attempts_total is not None:
            state.attempts_total = int(attempts_total)

        if continuation_count is not None:
            state.continuation_count = int(continuation_count)

        if budget_used_tokens is not None:
            state.budget_used_tokens = int(budget_used_tokens)

        if last_model is not None:
            state.last_model = str(last_model)

        if last_finish_reason is not None:
            state.last_finish_reason = str(last_finish_reason)

        if last_tokens_output is not None:
            state.last_tokens_output = int(last_tokens_output)

        if last_outcome is not None:
            state.last_outcome = last_outcome

        self.put(state)
        return state

"""
Output Manifest & Section Runtime State Contracts.
Deterministic, routing-agnostic schemas for Hermes Output Scaling.
"""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional, Dict, Any


class OutcomeType(str, Enum):
    COMPLETE = "COMPLETE"
    TRUNCATED = "TRUNCATED"
    STRUCTURALLY_INVALID = "STRUCTURALLY_INVALID"
    SEMANTICALLY_INCOMPLETE = "SEMANTICALLY_INCOMPLETE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    NO_PROGRESS = "NO_PROGRESS"


class SectionStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    IN_FLIGHT = "IN_FLIGHT"
    STORED_FINAL = "STORED_FINAL"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class ScalerStatus(str, Enum):
    DONE = "DONE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


@dataclass(frozen=True)
class OutputSection:
    section_id: str
    requirement_id: str
    title: str
    intent: str
    must_cover: List[str]
    depends_on: List[str] = field(default_factory=list)
    expected_shape: str = "structured_markdown"
    priority: str = "medium"
    budget_hint: Optional[int] = None
    max_continuations: int = 2

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutputSection":
        return cls(
            section_id=str(data.get("section_id", "")),
            requirement_id=str(data.get("requirement_id", "")),
            title=str(data.get("title", "")),
            intent=str(data.get("intent", "")),
            must_cover=list(data.get("must_cover", [])),
            depends_on=list(data.get("depends_on", [])),
            expected_shape=str(data.get("expected_shape", "structured_markdown")),
            priority=str(data.get("priority", "medium")),
            budget_hint=data.get("budget_hint"),
            max_continuations=int(data.get("max_continuations", 2)),
        )


@dataclass(frozen=True)
class OutputManifest:
    manifest_id: str
    version: str
    goal: str
    sections: List[OutputSection] = field(default_factory=list)
    global_acceptance: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    order_policy: str = "topological"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutputManifest":
        sections = [
            OutputSection.from_dict(s) if isinstance(s, dict) else s
            for s in data.get("sections", [])
        ]
        return cls(
            manifest_id=str(data.get("manifest_id", "")),
            version=str(data.get("version", "1.0")),
            goal=str(data.get("goal", "")),
            sections=sections,
            global_acceptance=list(data.get("global_acceptance", [])),
            constraints=list(data.get("constraints", [])),
            order_policy=str(data.get("order_policy", "topological")),
        )


@dataclass
class SectionRuntimeState:
    section_id: str
    status: SectionStatus = SectionStatus.PENDING
    chunks: List[str] = field(default_factory=list)
    accumulated_text: str = ""
    covered_items: List[str] = field(default_factory=list)
    remaining_items: List[str] = field(default_factory=list)
    attempts_total: int = 0
    continuation_count: int = 0
    budget_used_tokens: int = 0
    last_model: str = ""
    last_finish_reason: str = ""
    last_tokens_output: int = 0
    last_outcome: Optional[OutcomeType] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, SectionStatus) else self.status
        d["last_outcome"] = self.last_outcome.value if isinstance(self.last_outcome, OutcomeType) else self.last_outcome
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SectionRuntimeState":
        status_val = data.get("status", SectionStatus.PENDING)
        if isinstance(status_val, str):
            try:
                status_val = SectionStatus(status_val)
            except ValueError:
                status_val = SectionStatus.PENDING

        outcome_val = data.get("last_outcome")
        if isinstance(outcome_val, str):
            try:
                outcome_val = OutcomeType(outcome_val)
            except ValueError:
                outcome_val = None

        return cls(
            section_id=str(data.get("section_id", "")),
            status=status_val,
            chunks=list(data.get("chunks", [])),
            accumulated_text=str(data.get("accumulated_text", "")),
            covered_items=list(data.get("covered_items", [])),
            remaining_items=list(data.get("remaining_items", [])),
            attempts_total=int(data.get("attempts_total", 0)),
            continuation_count=int(data.get("continuation_count", 0)),
            budget_used_tokens=int(data.get("budget_used_tokens", 0)),
            last_model=str(data.get("last_model", "")),
            last_finish_reason=str(data.get("last_finish_reason", "")),
            last_tokens_output=int(data.get("last_tokens_output", 0)),
            last_outcome=outcome_val,
        )

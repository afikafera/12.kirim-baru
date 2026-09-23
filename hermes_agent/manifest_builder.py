"""
Deterministic Manifest Builder.
Transforms TaskPlanner plan into an immutable OutputManifest.
Zero LLM calls, deterministic O(N) mapping.
"""
import hashlib
import json
import logging
from typing import Dict, Any, List, Optional
from hermes_agent.output_manifest import OutputManifest, OutputSection

logger = logging.getLogger(__name__)


class ManifestBuilder:
    """
    Transforms structured Planner requirements and deliverables into
    a typed, immutable OutputManifest with deterministic dependency DAG.
    """

    def __init__(
        self,
        default_budget_hint: Optional[int] = None,
        default_max_continuations: int = 2,
    ):
        self.default_budget_hint = default_budget_hint
        self.default_max_continuations = default_max_continuations

    @staticmethod
    def _generate_manifest_id(goal: str, plan: Dict[str, Any]) -> str:
        """Deterministic manifest ID based on goal and plan content hash."""
        seed = f"{goal}::{json.dumps(plan, sort_keys=True, default=str)}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
        return f"man_{digest}"

    def build(
        self,
        plan: Dict[str, Any],
        goal: str = "",
        budget_hint: Optional[int] = None,
        max_continuations: Optional[int] = None,
    ) -> OutputManifest:
        """
        Deterministically builds an OutputManifest from a validated Planner plan.
        """
        if not isinstance(plan, dict):
            plan = {}

        goal_text = str(plan.get("goal") or goal or "").strip()
        manifest_id = self._generate_manifest_id(goal_text, plan)
        effective_budget = budget_hint if budget_hint is not None else self.default_budget_hint
        effective_continuations = (
            max_continuations if max_continuations is not None else self.default_max_continuations
        )

        raw_delivs = plan.get("deliverables")
        if not isinstance(raw_delivs, list):
            raw_delivs = []

        # Build deliverable id -> description map
        deliv_map: Dict[str, str] = {}
        for d in raw_delivs:
            if isinstance(d, dict):
                did = str(d.get("id") or "").strip()
                desc = str(d.get("description") or did).strip()
                if did:
                    deliv_map[did] = desc
                    deliv_map[did.lower()] = desc
            elif isinstance(d, str) and d.strip():
                did = d.strip()
                deliv_map[did] = did
                deliv_map[did.lower()] = did

        raw_kr = plan.get("knowledge_required")
        if not isinstance(raw_kr, list):
            raw_kr = []

        # Filter valid requirement nodes
        valid_kr: List[Dict[str, Any]] = []
        for item in raw_kr:
            if isinstance(item, dict):
                valid_kr.append(item)

        sections: List[OutputSection] = []

        if valid_kr:
            # Step 1: Pre-map requirement IDs and topics to canonical section_ids
            req_to_sec: Dict[str, str] = {}
            for idx, item in enumerate(valid_kr):
                sec_id = f"S{idx + 1:03d}"
                rid = str(item.get("id") or f"req_{idx + 1}").strip()
                req_to_sec[rid] = sec_id
                req_to_sec[rid.lower()] = sec_id

                topic = str(item.get("topic") or "").strip()
                if topic:
                    req_to_sec[topic] = sec_id
                    req_to_sec[topic.lower()] = sec_id

            # Step 2: Build OutputSection for each requirement
            for idx, item in enumerate(valid_kr):
                sec_id = f"S{idx + 1:03d}"
                rid = str(item.get("id") or f"req_{idx + 1}").strip()
                topic = str(item.get("topic") or rid).strip()
                need = str(item.get("need") or "documentation").strip()
                priority = str(item.get("priority") or "medium").strip().lower()
                if priority not in ("high", "medium", "low"):
                    priority = "medium"

                # Build must_cover list: topic first, followed by produces_deliverable descriptions
                must_cover: List[str] = []
                must_cover_keys = set()

                def add_must_cover(value: str) -> None:
                    value = str(value or "").strip()
                    key = " ".join(value.split()).casefold()
                    if value and key not in must_cover_keys:
                        must_cover.append(value)
                        must_cover_keys.add(key)

                if topic:
                    add_must_cover(topic)
                else:
                    add_must_cover(rid)

                raw_produces = item.get("produces_deliverable")
                if isinstance(raw_produces, list):
                    for p in raw_produces:
                        pid = str(p or "").strip()
                        desc = deliv_map.get(pid) or deliv_map.get(pid.lower()) or pid
                        add_must_cover(desc)
                elif isinstance(raw_produces, str) and raw_produces.strip():
                    pid = raw_produces.strip()
                    desc = deliv_map.get(pid) or deliv_map.get(pid.lower()) or pid
                    add_must_cover(desc)

                # Translate depends_on requirements to section_ids
                raw_deps = item.get("depends_on")
                sec_deps: List[str] = []
                if isinstance(raw_deps, list):
                    for dep in raw_deps:
                        dep_str = str(dep or "").strip()
                        target_sec = req_to_sec.get(dep_str) or req_to_sec.get(dep_str.lower())
                        if target_sec and target_sec != sec_id and target_sec not in sec_deps:
                            sec_deps.append(target_sec)
                elif isinstance(raw_deps, str) and raw_deps.strip():
                    dep_str = raw_deps.strip()
                    target_sec = req_to_sec.get(dep_str) or req_to_sec.get(dep_str.lower())
                    if target_sec and target_sec != sec_id and target_sec not in sec_deps:
                        sec_deps.append(target_sec)

                sections.append(
                    OutputSection(
                        section_id=sec_id,
                        requirement_id=rid,
                        title=topic,
                        intent=need,
                        must_cover=must_cover,
                        depends_on=sec_deps,
                        expected_shape="structured_markdown",
                        priority=priority,
                        budget_hint=effective_budget,
                        max_continuations=effective_continuations,
                    )
                )

        else:
            # Deterministic Fallback when knowledge_required is empty
            if raw_delivs:
                # Map existing deliverables directly into sections
                for idx, d in enumerate(raw_delivs):
                    sec_id = f"S{idx + 1:03d}"
                    if isinstance(d, dict):
                        did = str(d.get("id") or f"deliv_{idx + 1}").strip()
                        desc = str(d.get("description") or did).strip()
                    else:
                        did = f"deliv_{idx + 1}"
                        desc = str(d).strip()

                    sections.append(
                        OutputSection(
                            section_id=sec_id,
                            requirement_id=did,
                            title=desc,
                            intent=f"Deliverable: {desc}",
                            must_cover=[desc],
                            depends_on=[],
                            expected_shape="structured_markdown",
                            priority="high",
                            budget_hint=effective_budget,
                            max_continuations=effective_continuations,
                        )
                    )
            else:
                # Absolute fallback when both knowledge_required and deliverables are empty
                fallback_title = goal_text if goal_text else "Direct Answer"
                sections.append(
                    OutputSection(
                        section_id="S001",
                        requirement_id="req_fallback_answer",
                        title=fallback_title,
                        intent="Comprehensive and direct answer fulfilling the goal",
                        must_cover=[fallback_title],
                        depends_on=[],
                        expected_shape="structured_markdown",
                        priority="high",
                        budget_hint=effective_budget,
                        max_continuations=effective_continuations,
                    )
                )

        # Global acceptance: clean planner success_criteria
        raw_sc = plan.get("success_criteria")
        global_acceptance: List[str] = []
        if isinstance(raw_sc, list):
            for sc in raw_sc:
                if isinstance(sc, (str, int, float)) and str(sc).strip():
                    global_acceptance.append(str(sc).strip())

        # Constraints: clean planner constraints
        raw_con = plan.get("constraints")
        constraints: List[str] = []
        if isinstance(raw_con, list):
            for c in raw_con:
                if isinstance(c, (str, int, float)) and str(c).strip():
                    constraints.append(str(c).strip())

        return OutputManifest(
            manifest_id=manifest_id,
            version="1.0",
            goal=goal_text,
            sections=sections,
            global_acceptance=global_acceptance,
            constraints=constraints,
            order_policy="topological",
        )

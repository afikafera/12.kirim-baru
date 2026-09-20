"""
Planner Contract Validator (Phase 1: Structural-Only).
Deterministic structural validation of TaskPlanner output before insertion into KnowledgeGraph.
Zero LLM dependencies, O(N) complexity.
"""
import re
import logging

logger = logging.getLogger(__name__)

RETRIEVAL_META_PATTERNS = [
    re.compile(r"^(?:how\s+to\s+(?:find|search|lookup|google|query|fetch|browse))\b", re.IGNORECASE),
    re.compile(r"^(?:cara\s+(?:mencari|menemukan|mencari\s+tahu))\b", re.IGNORECASE),
    re.compile(r"^(?:steps\s+to\s+(?:find|search|locate))\b", re.IGNORECASE),
    re.compile(r"^(?:where\s+to\s+(?:find|look|search))\b", re.IGNORECASE),
    re.compile(r"^(?:websites?|situs|sources?)\s+to\s+(?:use|check|visit|browse)\b", re.IGNORECASE),
]

EXPLICIT_AUDIT_GOAL_PATTERN = re.compile(
    r"\b(?:accuracy|accurate|methodology|credibility|credible|reliability|reliable|validity|"
    r"akurasi|akurat|metodologi|kredibilitas|kredibel|keabsahan|keaslian|validitas|keandalan)\b",
    re.IGNORECASE,
)

EXPLICIT_MARKET_DEPTH_GOAL_PATTERN = re.compile(
    r"\b(?:depth|order\s*book|liquidity|spread|kedalaman|likuiditas)\b",
    re.IGNORECASE,
)

CONSTRAINT_AUDIT_PATTERNS = [
    re.compile(
        r"\b(?:research|investigate|study|explore|examine|verify|verifying|confirm|confirmation|"
        r"audit|auditing|assess|assessing|validate|validating|check|checking|"
        r"verifikasi|mengonfirmasi|mengaudit|mengevaluasi|meneliti|mempelajari)\b"
        r".*?"
        r"\b(?:accuracy|credibility|integrity|primary\s+(?:data\s+)?source|primary\s+source|"
        r"third-?party(?:\s+aggregation)?|official\s+mirror|unofficial|data\s+source\s+origin|"
        r"data\s+aggregation|aggregat(?:e|ion)\s+(?:from|with)|"
        r"pricing\s+methodology|data\s+collection(?:\s+methodology)?|calculation\s+methodology|"
        r"akurasi|kredibilitas|integritas|sumber\s+primer|pihak\s+ketiga|resmi\s+atau\s+tidak|"
        r"agregasi\s+data|metodologi\s+(?:harga|perhitungan|pembaruan))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:documentation|faq|guidelines|terms\s+of\s+service|dokumen(?:tasi)?)\b"
        r".*?"
        r"\b(?:accuracy|data\s+integrity|updates?\s+and\s+accuracy|pricing\s+methodology|data\s+collection\s+methodology|"
        r"akurasi|integritas\s+data|metodologi\s+pembaruan)\b",
        re.IGNORECASE,
    ),
]

MARKET_DEPTH_AUXILIARY_PATTERN = re.compile(
    r"\b(?:market\s+depth|order\s*book(?:\s+depth|\s+liquidity)?|liquidity\s+and\s+depth|"
    r"depth\s+and\s+liquidity|bid-ask\s+spread|kedalaman\s+pasar)\b",
    re.IGNORECASE,
)

PREP_SOURCE_PATTERN = re.compile(
    r"\b(?:on|in|from|at|according\s+to|melalui|dari|di|menurut)\s+([A-Za-z0-9_.-]+)\b",
    re.IGNORECASE,
)

COMPARISON_GOAL_PATTERN = re.compile(
    r"\b(?:compare|comparison|versus|vs\.?|diff(?:erence)?|beda|bandingkan|perbandingan|komparasi)\b",
    re.IGNORECASE,
)

ATTRIBUTE_TOKENS = {
    "price", "pricing", "rate", "kurs", "harga", "nilai", "quote", "value",
    "market", "cap", "capitalization", "marketcap", "kapitalisasi",
    "timestamp", "time", "date", "waktu", "tanggal", "updated", "last",
    "volume", "volum", "trading", "trade", "24h", "change", "high", "low", "tertinggi", "terendah",
    "status", "prob", "probability", "odds", "probabilitas", "spread",
}

TEMPORAL_MARKERS = {
    "historical", "history", "historis", "riwayat", "past", "dulu", "kemarin",
    "2020", "2021", "2022", "2023", "2024", "2025",
}

MAX_REQUIREMENTS = 10

VALID_DELIVERABLE_TYPES = {"number", "string", "boolean", "list", "dict", "object"}


class PlannerContractValidator:
    """Deterministic structural validator for TaskPlanner output."""

    @staticmethod
    def normalize_topic(topic: str) -> str:
        return re.sub(r"\s+", " ", str(topic).strip().lower())

    @classmethod
    def canonical_id(cls, raw: any) -> str:
        if raw is None:
            return ""
        s = str(raw).strip().lower()
        s = re.sub(r"[^\w]", "_", s)
        s = re.sub(r"_+", "_", s)
        return s.strip("_")

    @classmethod
    def is_comparison_goal(cls, goal: str) -> bool:
        if not goal:
            return False
        return bool(COMPARISON_GOAL_PATTERN.search(str(goal)))

    @classmethod
    def is_retrieval_meta_procedure(cls, topic: str, need: str = "") -> bool:
        t = str(topic).strip()
        for pat in RETRIEVAL_META_PATTERNS:
            if pat.search(t):
                return True
        return False

    @classmethod
    def is_constraint_audit_meta_requirement(cls, topic: str, need: str = "", goal: str = "") -> bool:
        combined = f"{str(topic).strip()} {str(need).strip()}"
        if not (goal and EXPLICIT_AUDIT_GOAL_PATTERN.search(str(goal))):
            if any(pat.search(combined) for pat in CONSTRAINT_AUDIT_PATTERNS):
                return True
            if not (goal and EXPLICIT_MARKET_DEPTH_GOAL_PATTERN.search(str(goal))):
                if MARKET_DEPTH_AUXILIARY_PATTERN.search(combined):
                    return True
        return False

    @classmethod
    def _extract_entity_source_signature(cls, topic: str, goal: str = "") -> tuple:
        t_clean = re.sub(r"[^\w\s-]", " ", topic.lower())
        words = t_clean.split()
        if not words:
            return (None, None, None)

        source = None
        prep_match = PREP_SOURCE_PATTERN.search(topic)
        if prep_match:
            cand_src = prep_match.group(1).lower()
            if len(cand_src) > 2 and (not goal or cand_src in goal.lower() or cand_src.isalnum()):
                source = cand_src

        if not source and goal:
            first_word = words[0]
            if len(first_word) > 2 and first_word in goal.lower():
                source = first_word

        if not source:
            return (None, None, None)

        temporal = "historical" if any(w in TEMPORAL_MARKERS for w in words) else "current"

        stop = {
            "on", "in", "from", "at", "according", "to", "melalui", "dari", "di", "menurut",
            "official", "resmi", "live", "current", "latest", "terbaru", "saat", "ini",
            "get", "retrieve", "ambil", "data", "info", "information",
        }
        entity_words = [
            w for w in words
            if w != source and w not in stop and w not in ATTRIBUTE_TOKENS and w not in TEMPORAL_MARKERS
        ]

        if not entity_words:
            return (None, None, None)

        entity_sig = " ".join(entity_words)
        return (entity_sig, source, temporal)

    @classmethod
    def _collapse_atomic_entity_attributes(cls, nodes: list, goal: str = "") -> list:
        if len(nodes) <= 1:
            return nodes

        depended_on_targets = set()
        for n in nodes:
            for dep in n.get("depends_on", []):
                dep_str = str(dep).strip()
                depended_on_targets.add(dep_str)
                depended_on_targets.add(cls.canonical_id(dep_str))
                depended_on_targets.add(cls.normalize_topic(dep_str))

        grouped = {}
        passthrough = []

        for n in nodes:
            t = n.get("topic", "")
            nid = n.get("id", "")
            deps = n.get("depends_on", [])
            if deps or t in depended_on_targets or nid in depended_on_targets or cls.canonical_id(nid) in depended_on_targets:
                passthrough.append(n)
                continue

            entity_sig, source_sig, temporal = cls._extract_entity_source_signature(t, goal=goal)
            if not entity_sig or not source_sig:
                passthrough.append(n)
                continue

            key = (entity_sig, source_sig, temporal)
            grouped.setdefault(key, []).append(n)

        result = []
        for key, group in grouped.items():
            if len(group) == 1:
                result.append(group[0])
            else:
                primary = group[0]
                all_needs = []
                all_produces = list(primary.get("produces_deliverable", []))
                for item in group:
                    need_val = str(item.get("need", "")).strip()
                    if need_val and need_val not in all_needs:
                        all_needs.append(need_val)
                    if item.get("priority") == "high":
                        primary["priority"] = "high"
                    for p in item.get("produces_deliverable", []):
                        if p not in all_produces:
                            all_produces.append(p)
                primary["need"] = "; ".join(all_needs) if all_needs else primary.get("need", "")
                primary["produces_deliverable"] = all_produces
                result.append(primary)

        result.extend(passthrough)
        return result

    @classmethod
    def validate(cls, plan: any, goal: str = "") -> dict:
        if not isinstance(plan, dict):
            logger.warning("[plan_validator] Input is not a dict; generating fallback.")
            return cls._fallback(goal)

        goal_text = str(plan.get("goal") or goal or "").strip()

        raw_delivs = plan.get("deliverables")
        if not isinstance(raw_delivs, list):
            raw_delivs = []

        seen_deliv_ids = set()
        for d in raw_delivs:
            if isinstance(d, dict) and d.get("id") is not None:
                cid = cls.canonical_id(d.get("id"))
                if cid:
                    if cid in seen_deliv_ids:
                        logger.warning(f"[plan_validator] Duplicate deliverable.id detected: {cid}; validation failure.")
                        return cls._fallback(goal_text)
                    seen_deliv_ids.add(cid)

        validated_deliverables = []
        deliv_id_set = set()
        for idx, d in enumerate(raw_delivs):
            if isinstance(d, dict):
                raw_id = d.get("id")
                cid = cls.canonical_id(raw_id) if raw_id is not None else ""
                if not cid:
                    desc_candidate = cls.canonical_id(d.get("description", ""))
                    cid = desc_candidate if desc_candidate else f"deliverable_{idx + 1}"

                if cid in deliv_id_set:
                    logger.warning(f"[plan_validator] Duplicate deliverable.id detected: {cid}; validation failure.")
                    return cls._fallback(goal_text)
                deliv_id_set.add(cid)

                raw_type = str(d.get("type") or "").strip().lower()
                dtype = raw_type if raw_type in VALID_DELIVERABLE_TYPES else "string"
                desc = str(d.get("description") or cid).strip()

                validated_deliverables.append({
                    "id": cid,
                    "type": dtype,
                    "description": desc,
                })
            elif isinstance(d, (str, int, float)):
                desc = str(d).strip()
                if not desc:
                    continue
                cid = cls.canonical_id(desc)
                if not cid or len(cid) > 50:
                    cid = f"deliverable_{idx + 1}"
                base_cid = cid
                counter = 1
                while cid in deliv_id_set:
                    counter += 1
                    cid = f"{base_cid}_{counter}"
                deliv_id_set.add(cid)

                validated_deliverables.append({
                    "id": cid,
                    "type": "string",
                    "description": desc,
                })

        constraints = [
            str(c).strip() for c in plan.get("constraints", [])
            if isinstance(c, (str, int, float)) and str(c).strip()
        ]
        success_criteria = [
            str(s).strip() for s in plan.get("success_criteria", [])
            if isinstance(s, (str, int, float)) and str(s).strip()
        ]

        try:
            confidence = float(plan.get("confidence", 0.7))
            confidence = max(0.0, min(1.0, confidence))
        except (ValueError, TypeError):
            confidence = 0.7

        raw_kr = plan.get("knowledge_required")
        if not isinstance(raw_kr, list):
            raw_kr = []

        seen_explicit_req_ids = set()
        for item in raw_kr:
            if isinstance(item, dict) and item.get("id") is not None and str(item.get("topic") or "").strip():
                cid = cls.canonical_id(item.get("id"))
                if cid:
                    if cid in seen_explicit_req_ids:
                        logger.warning(f"[plan_validator] Duplicate requirement.id detected: {cid}; validation failure.")
                        return cls._fallback(goal_text)
                    seen_explicit_req_ids.add(cid)

        valid_nodes = []
        seen_normalized_topics = {}
        used_req_ids = set(seen_explicit_req_ids)
        existing_deliv_ids = {d["id"] for d in validated_deliverables}

        for item in raw_kr:
            if not isinstance(item, dict):
                continue

            topic = str(item.get("topic") or "").strip()
            if not topic:
                continue

            need = str(item.get("need") or "documentation").strip()
            if not need:
                need = "documentation"

            if cls.is_retrieval_meta_procedure(topic, need):
                logger.info(f"[plan_validator] Pruning retrieval meta-procedure: {topic}")
                continue

            if cls.is_constraint_audit_meta_requirement(topic, need, goal=goal_text):
                logger.info(f"[plan_validator] Pruning constraint audit meta-requirement: {topic}")
                continue

            clean_produces = []
            raw_produces = item.get("produces_deliverable")
            if isinstance(raw_produces, list):
                for p in raw_produces:
                    cp = cls.canonical_id(p)
                    if cp in existing_deliv_ids and cp not in clean_produces:
                        clean_produces.append(cp)

            norm_topic = cls.normalize_topic(topic)
            if norm_topic in seen_normalized_topics:
                canonical_node = seen_normalized_topics[norm_topic]
                if need and need not in canonical_node["need"]:
                    canonical_node["need"] = f"{canonical_node['need']}; {need}"
                for p in clean_produces:
                    if p not in canonical_node.get("produces_deliverable", []):
                        canonical_node["produces_deliverable"].append(p)
                continue

            raw_req_id = item.get("id")
            if raw_req_id is not None and str(raw_req_id).strip():
                req_id = cls.canonical_id(raw_req_id)
            else:
                base_id = cls.canonical_id(topic)
                if not base_id:
                    base_id = f"req_{len(valid_nodes) + 1}"
                req_id = base_id
                counter = 1
                while req_id in used_req_ids:
                    counter += 1
                    req_id = f"{base_id}_{counter}"
            used_req_ids.add(req_id)

            priority = str(item.get("priority") or "medium").strip().lower()
            if priority not in ("high", "medium", "low"):
                priority = "medium"

            status = str(item.get("status") or "missing").strip().lower()
            if status not in ("missing", "found", "planned"):
                status = "missing"

            deps = item.get("depends_on", [])
            if not isinstance(deps, list):
                deps = []
            clean_deps = [str(d).strip() for d in deps if isinstance(d, (str, int, float)) and str(d).strip()]

            node = {
                "id": req_id,
                "topic": topic,
                "need": need,
                "priority": priority,
                "status": status,
                "produces_deliverable": clean_produces,
                "depends_on": clean_deps,
            }
            valid_nodes.append(node)
            seen_normalized_topics[norm_topic] = node

        valid_nodes = cls._collapse_atomic_entity_attributes(valid_nodes, goal=goal_text)

        sanitized_overflow = False
        original_count = len(valid_nodes)
        if len(valid_nodes) > MAX_REQUIREMENTS:
            logger.warning(
                f"[plan_validator] Requirements count ({len(valid_nodes)}) exceeds MAX_REQUIREMENTS ({MAX_REQUIREMENTS}). "
                f"Truncating to top {MAX_REQUIREMENTS} nodes."
            )
            valid_nodes = valid_nodes[:MAX_REQUIREMENTS]
            sanitized_overflow = True

        if not valid_nodes:
            logger.warning("[plan_validator] No valid requirements remained after validation; using fallback.")
            return cls._fallback(goal_text)

        target_to_node = {}
        for n in valid_nodes:
            target_to_node[n["id"]] = n
            target_to_node[cls.canonical_id(n["id"])] = n
            target_to_node[n["topic"]] = n
            target_to_node[cls.normalize_topic(n["topic"])] = n

        for node in valid_nodes:
            filtered_deps = []
            for d in node["depends_on"]:
                target = (
                    target_to_node.get(d)
                    or target_to_node.get(cls.canonical_id(d))
                    or target_to_node.get(cls.normalize_topic(d))
                )
                if target is not None and target is not node:
                    if d not in filtered_deps:
                        filtered_deps.append(d)
            node["depends_on"] = filtered_deps

        cls._break_cycles(valid_nodes)

        # Invariants I7-I11 (Outcome Graph Reachability & Authority) apply to Outcome Contract plans:
        # A plan is evaluated as an Outcome Graph if:
        # 1. Modern structured deliverables are declared (dict objects with id/type/desc), AND
        # 2. Requirements participate in outcome contract (at least one node explicitly declares produces_deliverable).
        # Legacy plans (string deliverables or missing produces_deliverable annotations) bypass reachability fail-closed.
        has_structured_deliverables = any(isinstance(d, dict) for d in raw_delivs)
        has_any_produces_field = any(
            "produces_deliverable" in item
            for item in raw_kr
            if isinstance(item, dict)
        )

        if has_structured_deliverables and has_any_produces_field and validated_deliverables:
            # 6. Invariant I11: Multi-Producer Authority Semantics
            # Non-comparison query with >1 producer for the same deliverable -> validation failure / fallback
            is_comparison = cls.is_comparison_goal(goal_text)
            producers_by_deliv = {}
            for node in valid_nodes:
                for d_id in node.get("produces_deliverable", []):
                    producers_by_deliv.setdefault(d_id, []).append(node)

            if not is_comparison:
                for d_id, p_nodes in producers_by_deliv.items():
                    if len(p_nodes) > 1:
                        logger.warning(
                            f"[plan_validator] Non-comparison goal has {len(p_nodes)} producers for deliverable '{d_id}'; "
                            f"validation failure (no positional guessing)."
                        )
                        return cls._fallback(goal_text)

            # 7. Invariants I8 & I9: Backward Reachability & Dead Requirement Pruning
            active_deliv_ids = {d["id"] for d in validated_deliverables}
            active_producers = [
                n for n in valid_nodes
                if any(d_id in active_deliv_ids for d_id in n.get("produces_deliverable", []))
            ]

            if validated_deliverables and not active_producers:
                logger.warning(
                    "[plan_validator] Deliverables declared but zero active producers found; validation failure."
                )
                return cls._fallback(goal_text)

            target_to_node = {}
            for n in valid_nodes:
                target_to_node[n["id"]] = n
                target_to_node[cls.canonical_id(n["id"])] = n
                target_to_node[n["topic"]] = n
                target_to_node[cls.normalize_topic(n["topic"])] = n

            reachable_node_ids = set()
            queue = list(active_producers)
            for p in active_producers:
                reachable_node_ids.add(id(p))

            while queue:
                curr = queue.pop(0)
                for dep_ref in curr.get("depends_on", []):
                    target = (
                        target_to_node.get(dep_ref)
                        or target_to_node.get(cls.canonical_id(dep_ref))
                        or target_to_node.get(cls.normalize_topic(dep_ref))
                    )
                    if target is not None and id(target) not in reachable_node_ids:
                        reachable_node_ids.add(id(target))
                        queue.append(target)

            retained_nodes = [n for n in valid_nodes if id(n) in reachable_node_ids]
            if len(retained_nodes) < len(valid_nodes):
                pruned_count = len(valid_nodes) - len(retained_nodes)
                logger.info(
                    f"[plan_validator] Pruned {pruned_count} dead requirement node(s) not reachable from any deliverable."
                )
                valid_nodes = retained_nodes

            if not valid_nodes:
                logger.warning("[plan_validator] No valid reachable requirements remained; using fallback.")
                return cls._fallback(goal_text)

            # 8. Invariant I7: Reverse Producer Check / Orphan Deliverables Check
            active_produced_delivs = set()
            for n in valid_nodes:
                for p in n.get("produces_deliverable", []):
                    active_produced_delivs.add(p)

            for d in validated_deliverables:
                if d["id"] not in active_produced_delivs:
                    logger.warning(
                        f"[plan_validator] Orphan deliverable detected: '{d['id']}' has no active producer in retained nodes; "
                        f"validation failure."
                    )
                    return cls._fallback(goal_text)

        validated_plan = {
            "goal": goal_text,
            "deliverables": validated_deliverables,
            "knowledge_required": valid_nodes,
            "constraints": constraints,
            "success_criteria": success_criteria,
            "confidence": confidence,
        }

        if sanitized_overflow:
            validated_plan["sanitized_overflow"] = True
            validated_plan["original_requirements_count"] = original_count

        if plan.get("planner_fallback"):
            validated_plan["planner_fallback"] = True

        return validated_plan

    @classmethod
    def _break_cycles(cls, nodes: list):
        target_to_node = {}
        for n in nodes:
            target_to_node[n["id"]] = n
            target_to_node[cls.canonical_id(n["id"])] = n
            target_to_node[n["topic"]] = n
            target_to_node[cls.normalize_topic(n["topic"])] = n

        adj = {id(n): [] for n in nodes}
        for n in nodes:
            for d in list(n["depends_on"]):
                target = (
                    target_to_node.get(d)
                    or target_to_node.get(cls.canonical_id(d))
                    or target_to_node.get(cls.normalize_topic(d))
                )
                if target is not None and target is not n:
                    adj[id(n)].append((id(target), d))

        visited = {}
        nodes_by_id = {id(n): n for n in nodes}

        for n in nodes:
            nid = id(n)
            if visited.get(nid, 0) == 0:
                cls._dfs_cycle_break(nid, adj, visited, [], nodes_by_id)

    @classmethod
    def _dfs_cycle_break(cls, u: int, adj: dict, visited: dict, path: list, nodes_by_id: dict):
        visited[u] = 1
        path.append(u)

        for v, dep_ref in list(adj.get(u, [])):
            state = visited.get(v, 0)
            if state == 1:
                u_node = nodes_by_id[u]
                v_node = nodes_by_id[v]
                logger.warning(
                    f"[plan_validator] Circular dependency detected: {u_node.get('topic', u)} -> "
                    f"{v_node.get('topic', v)} (via '{dep_ref}'). Breaking cycle."
                )
                adj[u] = [edge for edge in adj[u] if edge[0] != v]
                if dep_ref in u_node["depends_on"]:
                    u_node["depends_on"].remove(dep_ref)
            elif state == 0:
                cls._dfs_cycle_break(v, adj, visited, path, nodes_by_id)

        path.pop()
        visited[u] = 2

    @classmethod
    def _fallback(cls, goal: str) -> dict:
        g = goal.strip() if goal else "research goal"
        return {
            "goal": g,
            "deliverables": [
                {
                    "id": "answer",
                    "type": "string",
                    "description": "Direct answer to the research goal",
                }
            ],
            "knowledge_required": [
                {
                    "id": "req_1",
                    "topic": g,
                    "need": "general information",
                    "priority": "high",
                    "produces_deliverable": ["answer"],
                    "depends_on": [],
                    "status": "missing",
                }
            ],
            "constraints": [],
            "success_criteria": ["question answered"],
            "confidence": 0.5,
            "planner_fallback": True,
        }

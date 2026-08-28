import json
import os
import tempfile
import shutil
import fcntl
from datetime import datetime
from collections import defaultdict


class KnowledgeGraph:

    GRAPH_FILE = os.path.expanduser("~/research-assistant/data/knowledge_graph.json")

    VALID_RELATIONS = {
        "requires", "depends_on", "uses", "contains",
        "produces", "controls", "measures", "references",
        "implements", "similar_to", "outputs",
    }

    VALID_STATUSES = {
        "unknown", "planned", "searching", "found", "verified",
        "partial", "failed", "conflicted",
    }

    NODE_TYPES = {
        "project", "component", "ic", "procedure", "concept",
        "formula", "api", "code", "hardware", "datasheet", "unknown",
    }

    SOURCE_QUALITY = {
        "datasheet": 1.0, "pdf": 0.95, "official_docs": 0.9,
        "manual": 0.85, "spec_table": 0.8, "github": 0.75,
        "forum": 0.5, "tutorial": 0.4, "video": 0.3, "other": 0.3,
    }

    def __init__(self):
        self._lock_file = self.GRAPH_FILE + ".lock"
        os.makedirs(os.path.dirname(self.GRAPH_FILE), exist_ok=True)
        self._lock_fd = open(self._lock_file, "a+")
        fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            self.graph = self._load()
        except Exception:
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
            self._lock_fd.close()
            raise

    def _release_lock(self):
        fd = getattr(self, "_lock_fd", None)
        if fd is None:
            return

        self._lock_fd = None

        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        finally:
            fd.close()

    def close(self):
        fd = getattr(self, "_lock_fd", None)
        if fd is not None:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
            finally:
                fd.close()
                self._lock_fd = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _load(self) -> dict:
        if os.path.exists(self.GRAPH_FILE):
            with open(self.GRAPH_FILE) as f:
                data = json.load(f)
                for node in data.get("nodes", {}).values():
                    rels = node.get("relations", {})
                    if not isinstance(rels, defaultdict):
                        node["relations"] = defaultdict(list, rels)
                data["_edge_index"] = set(tuple(e) for e in data.get("_edge_index", []))
                return data
        return {"nodes": {}, "edges": [], "_edge_index": set()}

    def add_node(self, topic: str, node_type: str = "unknown", status: str = "planned", confidence: float = 0.5):
        if topic not in self.graph["nodes"]:
            self.graph["nodes"][topic] = {
                "type": node_type if node_type in self.NODE_TYPES else "unknown",
                "status": status if status in self.VALID_STATUSES else "planned",
                "confidence": confidence,
                "facts": [],
                "relations": defaultdict(list),
                "metadata": {
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "search_count": 0,
                    "last_search_at": None,
                    "last_source": None,
                    "evidence_count": 0,
                    "verified_count": 0,
                    "conflict_count": 0,
                },
            }

    def update_status(self, topic: str, status: str):
        if topic in self.graph["nodes"] and status in self.VALID_STATUSES:
            self.graph["nodes"][topic]["status"] = status
            self.graph["nodes"][topic]["metadata"]["updated_at"] = datetime.now().isoformat()

    def increment_search(self, topic: str, source: str = None):
        if topic in self.graph["nodes"]:
            m = self.graph["nodes"][topic]["metadata"]
            m["search_count"] += 1
            m["last_search_at"] = datetime.now().isoformat()
            if source: m["last_source"] = source

    def add_fact(self, topic: str, field: str, value, source: str = "unknown",
                 source_type: str = "other", confidence: float = 0.5):
        if topic not in self.graph["nodes"]:
            self.add_node(topic)
        facts = self.graph["nodes"][topic]["facts"]
        for f in facts:
            if f["field"] == field and str(f["value"]) == str(value) and f["source"] == source:
                return
        facts.append({
            "field": field, "value": value,
            "source": source, "source_type": source_type,
            "confidence": confidence,
        })
        self.graph["nodes"][topic]["metadata"]["evidence_count"] = len(facts)

    def get_facts(self, topic: str) -> list:
        return self.graph["nodes"].get(topic, {}).get("facts", [])

    def get_best_fact(self, topic: str, field: str):
        facts = self.get_facts(topic)
        best, best_score = None, -1
        for f in facts:
            if f["field"] == field:
                sq = self.SOURCE_QUALITY.get(f["source_type"], 0.3)
                score = f["confidence"] * 0.6 + sq * 0.4
                if score > best_score:
                    best_score, best = score, f
        return best

    def add_relation(self, source: str, relation: str, target: str, confidence: float = 0.7):
        if relation not in self.VALID_RELATIONS:
            relation = "references"
        self.add_node(source)
        self.add_node(target)
        if target not in self.graph["nodes"][source]["relations"][relation]:
            self.graph["nodes"][source]["relations"][relation].append(target)
        ek = (source, relation, target)
        if ek not in self.graph["_edge_index"]:
            self.graph["_edge_index"].add(ek)
            self.graph["edges"].append({"from": source, "to": target, "type": relation, "confidence": confidence})

    def get_relations(self, topic: str) -> dict:
        return dict(self.graph["nodes"].get(topic, {}).get("relations", {}))

    def learn(self, topic: str, facts: dict, plan: dict = None):
        self.add_node(topic)
        self.update_status(topic, "found")
        self.increment_search(topic)
        for field, v in facts.items():
            if isinstance(v, dict) and v.get("value"):
                self.add_fact(topic=topic, field=field, value=v["value"],
                              source=v.get("source", "unknown"),
                              source_type=v.get("source_type", "other"), confidence=0.7)
        if plan:
            for k in plan.get("knowledge_required", []):
                if k.get("topic") == topic and k.get("depends_on"):
                    for dep in k["depends_on"]:
                        self.add_relation(topic, "depends_on", dep)
        self.graph["nodes"][topic]["metadata"]["verified_count"] += 1
        self.save()

    # ==========================================
    # QUERY API
    # ==========================================

    def find_gaps(self, topic: str) -> list:
        """Semua node yang belum selesai (found/verified)."""
        gaps = []
        for rel, targets in dict(self.graph["nodes"].get(topic, {}).get("relations", {})).items():
            if rel in ("requires", "depends_on"):
                for t in targets:
                    st = self.graph["nodes"].get(t, {}).get("status", "unknown")
                    if st not in ("found", "verified"):
                        gaps.append({"topic": t, "relation": rel, "status": st})
        return gaps

    def ready_nodes(self, topic: str) -> list:
        """Node yang siap dikerjakan (gap + semua dependensi terpenuhi)."""
        gaps = self.find_gaps(topic)
        ready = []
        for g in gaps:
            t = g["topic"]
            tn = self.graph["nodes"].get(t, {})
            if tn.get("status") not in ("planned", "unknown", "failed", "partial"):
                continue
            all_met = True
            for rel, targets in tn.get("relations", {}).items():
                if rel in ("requires", "depends_on"):
                    for d in targets:
                        if self.graph["nodes"].get(d, {}).get("status") not in ("found", "verified"):
                            all_met = False
            if all_met:
                ready.append(g)
        return ready

    def blocked_nodes(self, topic: str) -> list:
        """Node yang belum selesai + masih menunggu dependency."""
        gaps = self.find_gaps(topic)
        ready_set = {r["topic"] for r in self.ready_nodes(topic)}
        blocked = []
        for g in gaps:
            if g["topic"] not in ready_set:
                t = g["topic"]
                tn = self.graph["nodes"].get(t, {})
                blockers = []
                for rel, targets in tn.get("relations", {}).items():
                    if rel in ("requires", "depends_on"):
                        for d in targets:
                            if self.graph["nodes"].get(d, {}).get("status") not in ("found", "verified"):
                                blockers.append(d)
                blocked.append({"topic": t, "status": g["status"], "blocked_by": blockers})
        return blocked

    # Alias
    next_tasks = ready_nodes

    def find_cycles(self) -> list:
        visited, cycles = set(), []
        def dfs(node, path):
            if node in path:
                cycles.append(path[path.index(node):] + [node])
                return
            if node in visited: return
            visited.add(node)
            for targets in self.graph["nodes"].get(node, {}).get("relations", {}).values():
                for t in targets:
                    dfs(t, path + [node])
        for node in self.graph["nodes"]:
            if node not in visited:
                dfs(node, [])
        return cycles

    def get_stats(self) -> dict:
        nodes = self.graph["nodes"]
        sc, tc = defaultdict(int), defaultdict(int)
        for n in nodes.values():
            sc[n.get("status", "unknown")] += 1
            tc[n.get("type", "unknown")] += 1
        return {
            "total_nodes": len(nodes), "status_count": dict(sc),
            "type_count": dict(tc), "edges": len(self.graph["edges"]),
            "cycles": len(self.find_cycles()),
        }

    def save(self):
        save_data = {"nodes": {}, "edges": self.graph["edges"], "_edge_index": list(self.graph["_edge_index"])}
        for topic, node in self.graph["nodes"].items():
            save_data["nodes"][topic] = {
                **{k: v for k, v in node.items() if k != "relations"},
                "relations": dict(node.get("relations", {})),
            }
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
            json.dump(save_data, tmp, indent=2, default=str)
            tmp_path = tmp.name
        shutil.move(tmp_path, self.GRAPH_FILE)
        self._release_lock()

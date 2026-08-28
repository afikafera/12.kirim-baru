import json
import re


class ResearchPlanner:

    INTENT_TARGETS = {
        "technical_spec": {
            "required": {"datasheet", "manual", "spec_table"},
            "optional": {"forum", "review", "video"},
            "search_queries": [
                "{product} datasheet PDF",
                "{product} specifications manual",
                "{product} T/S parameters Fs Vas Qts Xmax",
                "{product} technical data sheet download",
            ],
        },
        "diagnosis": {
            "required": {"forum", "manual", "tsb"},
            "optional": {"video", "review"},
            "search_queries": [
                "{product} troubleshooting fix",
                "{product} common causes solution",
                "{product} forum solved",
            ],
        },
        "tutorial": {
            "required": {"official_docs", "tutorial"},
            "optional": {"video", "forum"},
            "search_queries": [
                "{topic} tutorial step by step",
                "{topic} documentation guide",
                "{topic} how to setup",
            ],
        },
        "comparison": {
            "required": set(),
            "optional": {"review", "forum", "spec_table"},
            "search_queries": [
                "{product} vs comparison",
                "{product} review comparison",
                "{product} which is better",
            ],
        },
        "general": {
            "required": set(),
            "optional": {"any"},
            "search_queries": ["{query}"],
        }
    }

    DOMAIN_BONUS = {
        "audio": {"datasheet", "spec_table", "measurement", "catalog"},
        "otomotif": {"manual", "tsb", "catalog", "forum"},
        "networking": {"official_docs", "forum", "github"},
        "iot": {"github", "official_docs", "datasheet"},
    }

    def __init__(self, llm_analyzer):
        self.llm = llm_analyzer

    def detect_intent(self, query: str) -> str:
        q = query.lower()
        scores = {
            "diagnosis": 0,
            "technical_spec": 0,
            "tutorial": 0,
            "comparison": 0,
        }
        
        # Diagnosis: DTC codes + fault keywords
        if re.search(r'\b[PBCU]\d{4,5}\b', q, re.IGNORECASE):
            scores["diagnosis"] += 5
        for kw in ["dtc", "diagnosis", "diagnostic", "troubleshoot", "fault code",
                    "error code", "check engine", "malfunction", "not working",
                    "pressure too low", "pressure too high", "no communication"]:
            if kw in q:
                scores["diagnosis"] += 2
        for kw in ["symptom", "cause", "repair", "fix", "solve", "problem", "issue",
                    "leaking", "noise", "vibration", "warning light"]:
            if kw in q:
                scores["diagnosis"] += 1
        
        # Technical spec
        for kw in ["spesifikasi", "specification", "spec", "datasheet", "parameter",
                    "fs ", "vas ", "qts ", "xmax", "rms", "watt", "dimensi", "ukuran",
                    "weight", "berat", "frequency response", "impedance", "sensitivity"]:
            if kw in q:
                scores["technical_spec"] += 2
        
        # Tutorial
        for kw in ["cara", "tutorial", "how to", "setup", "setting", "konfigurasi",
                    "install", "pasang", "buat", "bikin", "step by step", "panduan"]:
            if kw in q:
                scores["tutorial"] += 2
        
        # Comparison
        for kw in ["vs ", "versus", "dibanding", "perbandingan", "compare",
                    "lebih baik", "mana yang", "pilih"]:
            if kw in q:
                scores["comparison"] += 2
        
        best = max(scores, key=scores.get)
        if scores[best] >= 2:
            return best
        return "general"

    def detect_domain(self, query: str) -> str:
        q = query.lower()
        if any(k in q for k in ["speaker", "audio", "subwoofer", "amplifier", "dsp", "acr", "sound", "bass"]):
            return "audio"
        if any(k in q for k in ["mobil", "mesin", "rem", "oli", "mercedes", "ferrari", "sl55", "f355", "engine",
                                  "dtc", "suspension", "transmission", "brake", "abc ", "r230"]):
            return "otomotif"
        if any(k in q for k in ["mikrotik", "router", "network", "queue", "bandwidth", "isp", "vlan"]):
            return "networking"
        if any(k in q for k in ["esp32", "arduino", "sensor", "iot", "dlms", "mqtt"]):
            return "iot"
        return "general"

    def extract_product(self, query: str) -> str:
        words = query.split()
        for i, w in enumerate(words):
            if w.upper() == w and len(w) >= 2 and not w.islower():
                start = max(0, i - 1)
                return " ".join(words[start:i + 3])
        return " ".join(words[:5])

    def plan(self, query: str) -> dict:
        intent = self.detect_intent(query)
        domain = self.detect_domain(query)
        target = self.INTENT_TARGETS.get(intent, self.INTENT_TARGETS["general"])
        product = self.extract_product(query)

        domain_extras = self.DOMAIN_BONUS.get(domain, set())
        required = target["required"] | (domain_extras & {"datasheet", "spec_table", "manual", "tsb", "official_docs"})

        search_queries = []
        for sq in target["search_queries"]:
            search_queries.append(
                sq.replace("{product}", product)
                  .replace("{topic}", query)
                  .replace("{problem}", query)
                  .replace("{query}", query)
            )

        return {
            "intent": intent,
            "domain": domain,
            "product": product,
            "required": required,
            "optional": target["optional"],
            "fallback_chain": {},
            "search_queries": search_queries,
            "search_count": 0,
            "max_searches": len(search_queries) + 3,
        }

    def classify_evidence(self, url: str, content: str) -> str:
        combined = (url + " " + (content or "")[:300]).lower()
        if any(k in combined for k in ["datasheet", "data sheet", "specification sheet"]):
            return "datasheet"
        if "pdf" in url.lower():
            return "pdf"
        if any(k in combined for k in ["manual", "user guide", "instruction", "owner"]):
            return "manual"
        if any(k in combined for k in ["t/s parameter", "thiele small", "fs ", "vas ", "qts ", "xmax", "sensitivity"]):
            return "spec_table"
        if any(k in combined for k in ["docs.", "documentation", "help.", "wiki."]):
            return "official_docs"
        if "forum." in url.lower() or "reddit.com" in url.lower() or "community." in url.lower():
            return "forum"
        if "tutorial" in combined or "how to" in combined or "panduan" in combined:
            return "tutorial"
        if "youtube.com" in url.lower() or "youtu.be" in url.lower():
            return "video"
        if "review" in combined or "test" in combined:
            return "review"
        if "measure" in combined or "pengukuran" in combined:
            return "measurement"
        if "catalog" in combined or "shop" in combined or "store" in combined or "jual" in combined:
            return "catalog"
        if "github.com" in url.lower():
            return "github"
        if "tsb" in combined or "technical service bulletin" in combined:
            return "tsb"
        return "other"


class EvidenceEvaluator:

    def evaluate(self, plan: dict, evidence_list: list) -> dict:
        required = plan.get("required", set())
        found_types = set()
        for e in evidence_list:
            found_types.add(e.get("evidence_type", "other"))

        covered = set()
        for req in required:
            if req in found_types:
                covered.add(req)

        coverage_pct = len(covered) / len(required) * 100 if required else 100
        diversity = len(found_types)
        diversity_score = min(diversity / 4 * 100, 100)
        combined_score = (coverage_pct * 0.7) + (diversity_score * 0.3)

        sufficient = coverage_pct >= 100 if required else True

        return {
            "sufficient": sufficient,
            "coverage_pct": coverage_pct,
            "diversity_score": diversity_score,
            "combined_score": combined_score,
            "covered": list(covered),
            "found_types": list(found_types),
        }

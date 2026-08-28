import json
import re
import logging

logger = logging.getLogger(__name__)


class CompletenessChecker:

    MAX_ADDITIONS = 5
    VALID_NEEDS = {
        "documentation", "datasheet", "example", "tutorial", "procedure",
        "specification", "reference", "configuration", "guide", "manual",
        "schematic", "code", "api", "comparison", "review",
    }

    def __init__(self, llm_analyzer=None):
        self.llm = llm_analyzer

    def _normalize(self, topic: str) -> str:
        t = topic.lower().strip()
        t = re.sub(r'[\-–—]', ' ', t)
        t = re.sub(r'\s+', ' ', t)
        return t

    def _valid_topic(self, topic: str) -> bool:
        if not topic or len(topic) < 3 or len(topic) > 80:
            return False
        words = topic.split()
        if len(words) > 10:
            return False
        return True

    def _valid_need(self, need: str) -> bool:
        return need.lower().strip() in self.VALID_NEEDS

    def _is_retrieval_procedure(self, topic: str, need: str = "") -> bool:
        """
        Reject requirements that describe HOW to retrieve information
        rather than knowledge required to satisfy the goal.
        """
        text = f"{topic} {need}".lower().strip()

        retrieval_patterns = (
            "how to ",
            "cara ",
            "langkah ",
            "steps to ",
            "ways to ",
            "website",
            "websites",
            "situs",
            "sites to use",
            "sources to use",
            "sources for",
            "where to find",
            "how do i ",
            "how do you ",
        )

        return any(pattern in text for pattern in retrieval_patterns)

    def check(self, plan: dict) -> dict:
        if not self.llm or not plan.get("knowledge_required"):
            return plan

        existing = [
            {"topic": k["topic"], "need": k["need"], "priority": k.get("priority", "medium")}
            for k in plan["knowledge_required"]
        ]
        goal = plan.get("goal", "")

        prompt = f"""Untuk goal berikut, reviewer sudah membuat daftar knowledge yang harus dicari:

Goal: {goal}
Knowledge yang sudah terdaftar:
{json.dumps(existing, indent=2)}

Tugas Anda: Apakah ada knowledge PENTING yang BELUM disebut?
- HANYA tambahkan jika TANPA knowledge tersebut goal TIDAK MUNGKIN tercapai.
- JANGAN tambahkan nice-to-have.
- JANGAN duplikasi yang sudah ada.
- Maksimum {self.MAX_ADDITIONS} knowledge tambahan.
- topic harus SPESIFIK dan bisa dicari (maks 80 karakter, maks 10 kata).
- need harus salah satu dari: {', '.join(sorted(self.VALID_NEEDS))}
- Kalau tidak ada yang kurang, return: {{"missing_knowledge": []}}

Format:
{{"missing_knowledge": [{{"topic": "...", "need": "...", "priority": "high|medium|low", "depends_on": [], "reason": "1 kalimat"}}], "confidence": 0.0-1.0}}

Return HANYA JSON."""

        try:
            result = self.llm.analyze(
                "Kamu knowledge reviewer. Return JSON only.",
                prompt, temperature=0.1
            )
            text = result["content"].strip().replace("```json", "").replace("```", "")
            review = json.loads(text)

            missing = review.get("missing_knowledge", [])
            confidence = review.get("confidence", 0.5)

            if not missing:
                logger.info(f"[completeness] ✓ no missing (conf={confidence:.2f})")
                return plan

            # Dedup dengan normalisasi
            existing_norm = {self._normalize(k["topic"]) for k in plan["knowledge_required"]}
            added = 0
            for m in missing:
                topic = m.get("topic", "")
                if not self._valid_topic(topic):
                    continue

                if self._is_retrieval_procedure(
                    topic,
                    m.get("need", ""),
                ):
                    logger.info(
                        f"[completeness] - retrieval procedure: {topic}"
                    )
                    continue

                if not self._valid_need(m.get("need", "")):
                    m["need"] = "documentation"

                norm = self._normalize(topic)
                if norm in existing_norm:
                    continue
                if added >= self.MAX_ADDITIONS:
                    break

                m["status"] = "missing"
                m.setdefault("depends_on", [])
                plan["knowledge_required"].append(m)
                existing_norm.add(norm)
                added += 1
                logger.info(f"[completeness] + {topic} [{m.get('priority','?')}] need={m['need']} reason={m.get('reason','')[:50]}")

            return plan
        except Exception as e:
            logger.warning(f"[completeness] fail: {e}")
            return plan

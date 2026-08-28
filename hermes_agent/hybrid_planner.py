import json
import logging

logger = logging.getLogger(__name__)


class HybridPlanner:
    """Hybrid: Rule-based dulu, LLM fallback kalau confidence rendah."""

    CONFIDENCE_THRESHOLD = 0.4  # Di bawah ini → panggil LLM

    def __init__(self, rule_planner, llm_analyzer):
        self.rule = rule_planner
        self.llm = llm_analyzer

    def plan(self, query: str) -> dict:
        # 1. Rule-based dulu
        plan = self.rule.plan(query)
        confidence = self._rule_confidence(query, plan)

        # 2. Kalau confidence cukup, return rule result
        if confidence >= self.CONFIDENCE_THRESHOLD:
            logger.info(f"[hybrid] rule confidence={confidence:.2f} → use rule")
            plan["planner_source"] = "rule"
            plan["planner_confidence"] = confidence
            return plan

        # 3. Confidence rendah → LLM fallback
        logger.info(f"[hybrid] rule confidence={confidence:.2f} → use LLM")
        llm_plan = self._llm_plan(query)

        # Merge: LLM untuk intent+product, rule untuk sisanya
        plan["intent"] = llm_plan.get("intent", plan["intent"])
        plan["domain"] = llm_plan.get("domain", plan["domain"])
        plan["product"] = llm_plan.get("product", plan["product"])
        plan["planner_source"] = "llm"
        plan["planner_confidence"] = confidence
        return plan

    def _rule_confidence(self, query: str, plan: dict) -> float:
        """Estimasi confidence rule-based planner."""
        confidence = 0.5  # Base

        # Intent confidence
        if plan["intent"] != "general":
            confidence += 0.2
        if plan["intent"] in ("diagnosis", "technical_spec"):
            confidence += 0.1  # Diagnosis & spec detection lebih akurat

        # Domain confidence
        if plan["domain"] != "general":
            confidence += 0.15

        # Product confidence
        product = plan.get("product", "")
        if product and product != query:
            confidence += 0.1

        return min(confidence, 1.0)

    def _llm_plan(self, query: str) -> dict:
        """Minta LLM untuk klasifikasi intent + domain + product."""
        prompt = f"""Analisis query berikut. Return JSON:
{{
    "intent": "diagnosis|technical_spec|tutorial|comparison|design|configuration|general",
    "domain": "otomotif|audio|networking|iot|programming|linux|crypto|general",
    "product": "nama produk utama (tanpa kata depan)",
    "keywords": ["kata kunci 1", "kata kunci 2", ...]
}}

Query: {query}

Return HANYA JSON."""

        try:
            result = self.llm.analyze(
                "Kamu query classifier. Return JSON only.",
                prompt, temperature=0
            )
            text = result["content"].strip().replace("```json", "").replace("```", "")
            return json.loads(text)
        except Exception as e:
            logger.warning(f"[hybrid] LLM fail: {e}")
            return {}

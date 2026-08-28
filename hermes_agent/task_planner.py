import json
import logging

logger = logging.getLogger(__name__)


class TaskPlanner:
    """Goal-based planner. Output: structured knowledge, bukan intent."""

    def __init__(self, llm_analyzer=None):
        self.llm = llm_analyzer

    def plan(self, goal: str, context: str = "") -> dict:
        if not self.llm:
            return self._fallback(goal)

        prompt = f"""Anda adalah Knowledge Planner. Breakdown PERTANYAAN AKTIF berikut menjadi pengetahuan yang harus dikumpulkan.

Active user question:
{goal}

Conversation context (gunakan hanya untuk memahami referensi seperti "ini", "tersebut", atau follow-up):
{context if context else "(none)"}

ATURAN CONTEXT:
- Pertanyaan aktif adalah sumber utama scope research.
- Conversation context hanya membantu memahami referensi/entitas yang tidak lengkap pada pertanyaan aktif.
- Pernyataan atau diagnosis dari assistant sebelumnya adalah CLAIM yang belum terverifikasi, bukan FACT.
- Jangan membuat requirement berdasarkan spekulasi assistant sebelumnya kecuali requirement tersebut memang diperlukan untuk MEMVERIFIKASI spekulasi itu.
- Jangan mengubah pertanyaan aktif menjadi research terhadap seluruh percakapan.

PENTING: Jangan berasumsi kategori/jenis produk dari kemiripan nama brand
atau model dengan produk lain yang lebih terkenal. Nama yang mirip bisa
merujuk produk yang SANGAT BERBEDA kategorinya (contoh: "ACR" bisa berarti
banyak hal berbeda tergantung konteks). Jika kategori produk TIDAK
disebutkan eksplisit di goal, topic yang dihasilkan harus tetap GENERIK
dan berbasis kata dalam goal itu sendiri (misalnya "product official
specification", "product category identification") -- JANGAN mengarang
topic teknis spesifik (interface, SDK, protokol, sertifikasi tertentu)
yang tidak didukung oleh kata dalam goal.

Return JSON:
{{
    "goal": "goal yang sudah dipertajam",
    "deliverables": ["output 1", "output 2", ...],
    "knowledge_required": [
        {{
            "topic": "topik spesifik (bisa dicari di mesin pencari)",
            "need": "apa yang dibutuhkan (datasheet, tutorial, procedure, specification, example, documentation)",
            "priority": "high|medium|low",
            "depends_on": ["topic lain yang harus ditemukan lebih dulu", ...],
            "status": "missing"
        }}
    ],
    "constraints": ["batasan atau preferensi"],
    "success_criteria": ["kriteria keberhasilan"],
    "confidence": 0.0-1.0
}}

Setiap topic harus SPESIFIK dan dapat dicari.
Gunakan bahasa Inggris untuk topic (lebih universal untuk search).
Return HANYA JSON."""

        try:
            result = self.llm.analyze(
                "Kamu knowledge planner. Return JSON only.",
                prompt, temperature=0.2
            )
            text = result["content"].strip().replace("```json", "").replace("```", "")
            return json.loads(text)
        except Exception as e:
            logger.warning(f"[task_planner] fail: {e}")
            return self._fallback(goal)

    def _fallback(self, goal: str) -> dict:
        return {
            "goal": goal,
            "deliverables": ["answer"],
            "knowledge_required": [
                {"topic": goal, "need": "general information", "priority": "high", "depends_on": [], "status": "missing"}
            ],
            "constraints": [],
            "success_criteria": ["question answered"],
            "confidence": 0.5,
            # Explicitly mark that structured planning failed.
            # Core must not treat this fallback as a normal low-confidence
            # plan and ask CompletenessChecker to invent new requirements.
            "planner_fallback": True,
        }

    def get_missing(self, plan: dict) -> list:
        knowledge = plan.get("knowledge_required", [])
        missing = [k for k in knowledge if k.get("status") == "missing"]
        found_topics = {k["topic"] for k in knowledge if k.get("status") == "found"}

        def sort_key(k):
            priority_order = {"high": 0, "medium": 1, "low": 2}
            deps_met = all(d in found_topics for d in k.get("depends_on", []))
            return (priority_order.get(k.get("priority"), 1), not deps_met)

        missing.sort(key=sort_key)
        return missing

    def mark_found(self, plan: dict, topic: str):
        for k in plan.get("knowledge_required", []):
            if k["topic"] == topic:
                k["status"] = "found"

    def is_complete(self, plan: dict) -> bool:
        return all(k.get("status") == "found" for k in plan.get("knowledge_required", []))

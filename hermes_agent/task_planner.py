import json
import re
import logging

from hermes_agent.llm_output_contract import llm_output_failure
from hermes_agent.plan_validator import PlannerContractValidator

logger = logging.getLogger(__name__)

MONTH_MAP = {
    "januari": "01", "january": "01", "jan": "01",
    "februari": "02", "february": "02", "feb": "02",
    "maret": "03", "march": "03", "mar": "03",
    "april": "04", "apr": "04",
    "mei": "05", "may": "05",
    "juni": "06", "june": "06", "jun": "06",
    "juli": "07", "july": "07", "jul": "07",
    "agustus": "08", "august": "08", "aug": "08",
    "september": "09", "sep": "09",
    "oktober": "10", "october": "10", "okt": "10", "oct": "10",
    "november": "11", "nov": "11",
    "desember": "12", "december": "12", "des": "12", "dec": "12"
}

def extract_date_anchor(text: str) -> str:
    """Extracts date in format YYYY-MM-DD, DD Month YYYY, or relative dates."""
    if not text:
        return ""
    m = re.search(r'\b(20\d\d)[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b', text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r'\b(0[1-9]|[12]\d|3[01])[-/](0[1-9]|1[0-2])[-/](20\d\d)\b', text)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.search(r'\b(0?[1-9]|[12]\d|3[01])\s+([A-Za-z]+)\s+(20\d\d)\b', text)
    if m:
        day = m.group(1).zfill(2)
        month_str = m.group(2).lower()
        year = m.group(3)
        if month_str in MONTH_MAP:
            return f"{year}-{MONTH_MAP[month_str]}-{day}"
    m = re.search(r'\b([A-Za-z]+)\s+(0?[1-9]|[12]\d|3[01]),?\s+(20\d\d)\b', text)
    if m:
        month_str = m.group(1).lower()
        day = m.group(2).zfill(2)
        year = m.group(3)
        if month_str in MONTH_MAP:
            return f"{year}-{MONTH_MAP[month_str]}-{day}"
    return ""

def extract_temporal_anchor(text: str) -> str:
    """Extracts year, month-year, or relative day anchors from text."""
    if not text:
        return ""
    date_anchor = extract_date_anchor(text)
    if date_anchor:
        return date_anchor
    m = re.search(r'\b(20\d\d)\b', text)
    if m:
        return m.group(1)
    m = re.search(r'\b(hari ini|today|saat ini|sekarang|current|kemarin|yesterday|besok|tomorrow)\b', text, re.I)
    if m:
        return m.group(1).lower()
    return ""

def extract_entity_anchor(text: str) -> str:
    """Extracts high-value core entity names like Bitcoin, Ethereum, Solana, etc."""
    if not text:
        return ""
    common_entities = [
        "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
        "binance", "coingecko", "coinmarketcap", "tokocrypto", "indodax"
    ]
    words = re.findall(r'\b[A-Za-z0-9_.-]+\b', text.lower())
    found = []
    for ent in common_entities:
        if ent in words:
            found.append(ent)
    return " ".join(found)

def inherit_entity_anchor(child_topic: str, parent_topic: str) -> str:
    """If child lacks entity present in parent, inject it into child."""
    parent_ent = extract_entity_anchor(parent_topic)
    child_ent = extract_entity_anchor(child_topic)
    if parent_ent and not child_ent:
        return f"{child_topic} {parent_ent}".strip()
    return child_topic

def inherit_date_anchor(child_topic: str, parent_topic: str) -> str:
    """If child lacks date anchor present in parent, inject it into child."""
    parent_date = extract_temporal_anchor(parent_topic)
    child_date = extract_temporal_anchor(child_topic)
    if parent_date and not child_date:
        return f"{child_topic} {parent_date}".strip()
    return child_topic

def deduplicate_anchors_in_topic(topic: str) -> str:
    """Clean up duplicated words/tokens in topic caused by multiple inheritances."""
    words = topic.split()
    seen = set()
    cleaned = []
    for w in words:
        wl = w.lower().strip("(),.")
        if wl not in seen or len(wl) <= 2:
            cleaned.append(w)
            if len(wl) > 2:
                seen.add(wl)
    return " ".join(cleaned)

def normalize_plan_entity_anchor(plan: dict, context: str = "", goal: str = "") -> dict:
    """
    Deterministically propagates entity & date anchors through dependency chains (P1).
    Ensures children inherit missing parent anchors and context anchors.
    """
    if not isinstance(plan, dict):
        return plan

    knowledge = plan.get("knowledge_required", [])
    topic_mapping = {}
    id_to_topic = {k.get("id"): k.get("topic") for k in knowledge if k.get("id") and k.get("topic")}

    for k in knowledge:
        orig_topic = k.get("topic", "")
        new_topic = orig_topic

        # 1. Inherit anchors from depends_on
        for dep in k.get("depends_on", []):
            resolved_dep_topic = id_to_topic.get(dep, dep)
            parent_topic = topic_mapping.get(resolved_dep_topic, resolved_dep_topic)

            # Inherit date anchor if parent has date and child does not
            new_topic = inherit_date_anchor(new_topic, parent_topic)
            # Inherit entity anchor if parent has entity and child does not
            new_topic = inherit_entity_anchor(new_topic, parent_topic)

        # 2. Inherit date anchor from goal/context if still missing
        if not extract_date_anchor(new_topic):
            context_date = extract_date_anchor(goal) or extract_date_anchor(context)
            if context_date:
                new_topic = f"{new_topic} {context_date}".strip()

        # 3. Inherit entity anchor from goal/context if still missing
        if not extract_entity_anchor(new_topic):
            context_ent = extract_entity_anchor(goal) or extract_entity_anchor(context)
            if context_ent:
                new_topic = f"{new_topic} {context_ent}".strip()

        new_topic = deduplicate_anchors_in_topic(new_topic)
        topic_mapping[orig_topic] = new_topic
        k["topic"] = new_topic

    return plan

class TaskPlanner:
    def __init__(self, llm):
        self.llm = llm

    @staticmethod
    def _normalize_planner_payload(raw) -> dict | None:
        """
        Deterministic, contract-aware payload normalization (P1-A).
        Handles native dict, markdown fences, </think> reasoning prefix,
        and bounded single-object JSON via JSONDecoder.raw_decode.
        Rejects non-dict JSON (lists, scalars), malformed JSON, and prose.
        """
        if isinstance(raw, dict):
            return raw

        if not isinstance(raw, str):
            return None

        text = raw.strip()
        if not text:
            return None

        # 1. Strip reasoning model thinking tags if present
        if "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        elif "<think>" in text:
            return None

        if not text:
            return None

        # 2. Try direct JSON parsing
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
            return None
        except Exception:
            pass

        # 3. Try markdown code fences ```json ... ``` or ``` ... ```
        fence_pattern = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.DOTALL)
        for match in fence_pattern.finditer(text):
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue

        # 4. Bounded extraction via json.JSONDecoder.raw_decode
        start_idx = text.find("{")
        while start_idx != -1:
            try:
                decoder = json.JSONDecoder()
                parsed, _ = decoder.raw_decode(text[start_idx:])
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
            start_idx = text.find("{", start_idx + 1)

        return None

    def plan(self, goal: str, context: str = "", max_attempts: int = 2) -> dict:
        prompt = f"""Kamu adalah Task Planner untuk Autonomous Research Agent.
Tugasmu adalah menganalisis research goal dan menghasilkan structured research plan.

Research Goal: {goal}
Context: {context if context else "None"}

INSTRUCTIONS:
1. Analisis apa saja informasi yang BENAR-BENAR DIBUTUHKAN untuk menjawab goal.
2. Identifikasi deliverables yang konkret (apa yang harus dihasilkan).
3. Buat daftar knowledge requirements yang spesifik dan terarah.
4. Tentukan dependensi antar knowledge requirements (apa yang harus dicari lebih dulu).
5. Definisikan constraints dan success criteria yang terukur.
6. HANYA rencanakan informasi yang eksplisit relevan untuk menjawab goal.
   JANGAN merencanakan audit, investigasi sekunder, verifikasi kredibilitas,
   metodologi agregasi, atau cross-check pihak ketiga KECUALI goal secara eksplisit
   memintanya (misal ada kata 'validasi', 'verifikasi', 'audit', 'kredibilitas').
   Fokus langsung ke data/fakta yang diminta user.
7. GROUNDING RULE (CRITICAL):
   - Scope research plan HANYA pada entitas, objek, parameter, dan sistem yang
     disebutkan secara eksplisit dalam goal atau context.
   - JANGAN PERNAH menambahkan sub-topik spekulatif dari domain yang berbeda.
   - JANGAN mengasumsikan sistem periferal yang tidak disebutkan.
   - Jika goal menyebut sistem spesifik, fokus HANYA pada sistem tersebut.
   - DILARANG menambahkan requirements tentang sub-sistem spekulatif
     yang tidak didukung oleh kata-kata dalam goal.

SUCCESS CRITERIA GROUNDING RULE:
- Setiap success criterion harus dapat ditelusuri langsung ke kata-kata dalam goal.
- DILARANG menambahkan kriteria yang mewajibkan konfirmasi sistem yang tidak diminta.
- Success criteria harus menguji apakah pertanyaan user terjawab, BUKAN apakah
  topik spekulatif yang kamu tambahkan sendiri terpenuhi.

SCOPE BOUNDARY:
- Rencanakan HANYA apa yang secara eksplisit diminta oleh goal atau didukung konteks.
- JANGAN berinisiatif meneliti sub-sistem atau parameter tambahan
  yang tidak didukung oleh kata-kata dalam goal.

Return JSON:
{{
    "goal": "goal yang sudah dipertajam",
    "deliverables": [
        {{
            "id": "canonical_snake_case_id",
            "type": "number|string|boolean|list|object",
            "description": "deskripsi deliverable yang jelas dan atomik"
        }}
    ],
    "knowledge_required": [
        {{
            "id": "req_canonical_snake_case_id",
            "topic": "topik spesifik (bisa dicari di mesin pencari)",
            "need": "apa yang dibutuhkan (datasheet, tutorial, procedure, specification, example, documentation)",
            "produces_deliverable": ["id_deliverable_yang_dihasilkan_oleh_node_ini"],
            "priority": "high|medium|low",
            "depends_on": ["id atau topic prerequisite yang harus ditemukan lebih dulu", ...],
            "status": "missing"
        }}
    ],
    "constraints": ["constraint 1", ...],
    "success_criteria": ["kriteria 1", ...],
    "confidence": 0.0-1.0
}}

OUTCOME CONTRACT & DELIVERABLES:
- Deliverables adalah item data konkret yang menjadi jawaban langsung untuk goal user.
- Setiap deliverable WAJIB memiliki "id" (snake_case unik), "type" (number|string|boolean|list|object), dan "description".
- Untuk NON-COMPARISON goal, setiap deliverable WAJIB diproduksi oleh TEPAT SATU requirement di "knowledge_required" melalui "produces_deliverable".
- Untuk COMPARISON goal, multi-producer diperbolehkan HANYA jika memang diperlukan secara semantik oleh struktur perbandingan.
- JANGAN menetapkan deliverable yang sama pada lebih dari satu requirement untuk NON-COMPARISON goal.
- JANGAN membuat deliverable yang tidak pernah diproduksi oleh requirement manapun.

SUCCESS CRITERIA:
- Setiap success criterion harus dapat ditelusuri langsung ke goal,
  active question, resolved context, atau prerequisite yang benar-benar
  dibutuhkan untuk menjawab.
- Kriteria harus berupa penyelesaian deliverable konkret atau verifikasi
  fakta penting, BUKAN meta-eksplorasi.

REQUIREMENT COHESION & GRANULARITY:
- ATOMIC ENTITY COHESION: Jika pertanyaan meminta beberapa deliverable,
  field data, nilai, atau atribut yang berasal dari subjek/entitas dan
  sumber logis yang sama (misalnya: probabilitas, judul pasar, dan
  tanggal resolusi untuk pasar pemilu di Polymarket), SELURUH kebutuhan
  tersebut WAJIB disatukan dalam SATU requirement (1 node).
  Rangkum semua kebutuhan field tersebut ke dalam "need".
  JANGAN memecah menjadi node terpisah untuk setiap field.
- SINGLE-TARGET FACT / SPECIFIC LOOKUP: Jika pertanyaan meminta nilai, harga,
  metrik, status, atau fakta dari entitas atau platform tertentu (misalnya:
  "Berapa harga Ethereum saat ini menurut CoinGecko?", "Berapa kurs USD di BCA?",
  "Harga Bitcoin menurut Binance"), plan WAJIB HANYA menghasilkan SATU knowledge
  requirement (1 node) untuk mengambil data dari platform/entitas tersebut.
  Platform yang disebut user diperlakukan sebagai sumber otoritatif yang diminta.
  JANGAN membuat requirement tambahan untuk meneliti dokumentasi/FAQ platform,
  mengaudit akurasi data platform, atau memverifikasi apakah platform menggunakan
  agregasi pihak ketiga, KECUALI jika user secara eksplisit meminta audit tersebut.
- NO PROCEDURAL DECOMPOSITION: JANGAN memecah proses pencarian ke dalam
  langkah-langkah prosedural seperti "identify market page",
  "extract details", dan "verify source". Satu requirement sudah mencakup
  menemukan bukti sekaligus mengekstrak seluruh field yang diminta.
- CONSTRAINTS ARE NOT REQUIREMENTS: Batasan sumber, platform, atau
  metodologi (seperti "Use Polymarket data only", "hanya dari situs resmi",
  "exclude third-party") adalah CONSTRAINTS. Masukkan batasan tersebut ke
  dalam array "constraints". JANGAN membuat node terpisah di
  "knowledge_required" untuk memverifikasi batasan tersebut.
- STRICT DEPENDENCY PREREQUISITES: Gunakan depends_on HANYA jika
  pencarian Topik B secara mutlak membutuhkan identitas, entitas, atau
  output spesifik yang baru bisa diketahui setelah Topik A selesai
  ditemukan. Jika entitas target sudah didefinisikan secara eksplisit
  pada pertanyaan aktif (misalnya: "Donald Trump 2028 U.S. presidential
  election according to Polymarket"), depends_on WAJIB [].

CONSTRAINTS:
- Batasan yang relevan, misal: "fokus sumber resmi", "hindari spekulasi".

PENTING:
- knowledge_required harus spesifik, BUKAN pertanyaan umum.
  BURUK: "apa itu LoRa?"
  BAIK: "Spesifikasi frekuensi LoRa SX1276 untuk region Indonesia AS923"
- depends_on menunjukkan urutan logis: jika B butuh output dari A, maka B depends_on A.
- priority: "high" untuk blocking info, "medium" untuk supporting, "low" untuk nice-to-have.
- Batasi knowledge_required maksimal 5-7 items agar riset fokus dan efisien.

JSON ONLY. Tanpa penjelasan, tanpa markdown block."""

        max_tokens_schedule = [1536, 3072]
        for attempt in range(1, max_attempts + 1):
            attempt_max_tokens = max_tokens_schedule[min(attempt - 1, len(max_tokens_schedule) - 1)]
            try:
                system_prompt = (
                    "Kamu adalah task planner JSON generator. "
                    "Keluarkan HANYA raw JSON object yang valid. "
                    "DILARANG keras menyertakan markdown code fence seperti ```json atau ```. "
                    "DILARANG menyertakan teks pembuka, penutup, atau analisis di luar JSON. "
                    "Format yang valid dimulai dengan '{' dan diakhiri dengan '}'."
                )
                user_query = f"{prompt}\n\nReturn HANYA JSON."
                result = self.llm.analyze(
                    system_prompt=system_prompt,
                    user_query=user_query,
                    temperature=0.2,
                    max_tokens=attempt_max_tokens
                )
            except Exception as e:
                logger.warning(
                    f"[task_planner] call failed (attempt {attempt}/{max_attempts}, max_tokens={attempt_max_tokens}): {e}"
                )
                continue

            if not isinstance(result, dict):
                logger.warning(
                    f"[task_planner] output contract failed (attempt {attempt}/{max_attempts}, max_tokens={attempt_max_tokens}): invalid_result_type"
                )
                continue

            # Check truncation across all content representations (P1-A)
            if str(result.get("finish_reason", "")).strip().lower() == "length":
                logger.warning(
                    f"[task_planner] output contract failed (attempt {attempt}/{max_attempts}, max_tokens={attempt_max_tokens}): length_truncated"
                )
                continue

            raw_content = result.get("content")

            if isinstance(raw_content, dict):
                candidate_dict = raw_content
            else:
                failure = llm_output_failure(result)
                if failure is not None:
                    logger.warning(
                        f"[task_planner] output contract failed (attempt {attempt}/{max_attempts}, max_tokens={attempt_max_tokens}): {failure}"
                    )
                    continue

                candidate_dict = self._normalize_planner_payload(raw_content)
                if candidate_dict is None:
                    logger.warning(
                        f"[task_planner] parse failed (attempt {attempt}/{max_attempts}, max_tokens={attempt_max_tokens}): no valid JSON object extracted"
                    )
                    continue

            try:
                logger.info(
                    "[PLANNER RAW] %r",
                    candidate_dict if isinstance(raw_content, dict) else raw_content,
                )
                plan = normalize_plan_entity_anchor(candidate_dict, context=context, goal=goal)
                # Unconditional canonical validation boundary (I12)
                plan = PlannerContractValidator.validate(plan, goal=goal)
                return plan
            except Exception as e:
                logger.warning(
                    f"[task_planner] parse failed (attempt {attempt}/{max_attempts}, max_tokens={attempt_max_tokens}): {e}"
                )
                if attempt == max_attempts:
                    return self._fallback(goal, context)

        logger.warning(f"[task_planner] all {max_attempts} attempts exhausted, falling back")
        return self._fallback(goal, context)

    def _fallback(self, goal: str, context: str = "") -> dict:
        plan = {
            "goal": goal,
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
                    "topic": goal,
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
        return normalize_plan_entity_anchor(plan, context=context, goal=goal)

    def get_next_topic(self, plan: dict) -> str:
        knowledge = plan.get("knowledge_required", [])
        missing = [k for k in knowledge if k.get("status") == "missing"]
        found_topics = {k["topic"] for k in knowledge if k.get("status") == "found"}
        found_ids = {k.get("id") for k in knowledge if k.get("status") == "found" and k.get("id")}
        found_all = found_topics | found_ids

        def sort_key(k):
            priority_order = {"high": 0, "medium": 1, "low": 2}
            deps_met = all(d in found_all for d in k.get("depends_on", []))
            return (priority_order.get(k.get("priority"), 1), not deps_met)

        missing.sort(key=sort_key)
        return missing[0]["topic"] if missing else None

    def mark_found(self, plan: dict, topic: str):
        for k in plan.get("knowledge_required", []):
            if k.get("topic") == topic or k.get("id") == topic:
                k["status"] = "found"

    def is_complete(self, plan: dict) -> bool:
        return self.get_next_topic(plan) is None

import json
import re
import logging

from hermes_agent.llm_output_contract import llm_output_failure

logger = logging.getLogger(__name__)


MONTHS_EN = r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)'
MONTHS_ID = r'(?:Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember)'
MONTHS = rf'(?:{MONTHS_EN}|{MONTHS_ID})'

DATE_PATTERNS = [
    re.compile(rf'\b{MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:\s*,\s*|\s+)\d{{4}}\b', re.IGNORECASE),
    re.compile(rf'\b\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTHS}(?:\s*,\s*|\s+)\d{{4}}\b', re.IGNORECASE),
    re.compile(r'\b\d{4}-\d{2}-\d{2}\b'),
    re.compile(rf'\b{MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?\b', re.IGNORECASE),
    re.compile(rf'\b\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTHS}\b', re.IGNORECASE),
    re.compile(rf'\b{MONTHS}\s+\d{{4}}\b', re.IGNORECASE),
]

ENTITY_PATTERN = re.compile(
    r'\b([A-Z]{2,})[ \t]+(\d[\dA-Za-z-]*)\b(?:[ \t]+([A-Z][a-zA-Z]*))?'
)

DESIGN_TOPIC_MARKERS = (
    "design", "tuning", "compatibility", "safety", "implementation",
    "port", "enclosure", "box",
)


def extract_date_anchor(text: str) -> str:
    if not text:
        return ""
    for pat in DATE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0)
    return ""


def extract_entity_tokens(context: str) -> list:
    if not context:
        return []
    match = ENTITY_PATTERN.search(context)
    if not match:
        return []
    return [g for g in match.groups() if g]


def _is_design_related(topic: str) -> bool:
    t = topic.lower()
    return any(marker in t for marker in DESIGN_TOPIC_MARKERS)


def _has_entity(topic: str, entity_tokens: list) -> bool:
    t = topic.lower()
    return all(tok.lower() in t for tok in entity_tokens)


def inherit_date_anchor(child_topic: str, parent_topic: str) -> str:
    parent_date = extract_date_anchor(parent_topic)
    if not parent_date:
        return child_topic

    if parent_date.lower() in child_topic.lower():
        return child_topic

    child_date = extract_date_anchor(child_topic)
    if child_date:
        return child_topic

    idx = parent_topic.lower().find(parent_date.lower())
    parent_prefix = parent_topic[:idx].strip()
    parent_prefix_words = parent_prefix.split()
    child_words = child_topic.split()

    if child_words and parent_prefix_words:
        first_cw = child_words[0].lower()
        parent_lowers = [pw.lower() for pw in parent_prefix_words]
        if first_cw in parent_lowers and first_cw != parent_lowers[0]:
            p_idx = parent_lowers.index(first_cw)
            missing_leading = parent_prefix_words[:p_idx]
            child_words = missing_leading + child_words
            child_topic = " ".join(child_words)

    match_count = 0
    for pw, cw in zip(parent_prefix_words, child_words):
        if pw.lower() == cw.lower():
            match_count += 1
        else:
            break

    if match_count > 0:
        parent_remaining_entity = []
        for w in parent_prefix_words[match_count:]:
            if w[0].isupper() and w.lower() not in [cw.lower() for cw in child_words]:
                parent_remaining_entity.append(w)
            else:
                break

        insert_parts = []
        if parent_remaining_entity:
            insert_parts.append(" ".join(parent_remaining_entity))
        insert_parts.append(parent_date)
        insert_str = " ".join(insert_parts)

        prefix = " ".join(child_words[:match_count])
        suffix = " ".join(child_words[match_count:])
        if suffix:
            return f"{prefix} {insert_str} {suffix}"
        else:
            return f"{prefix} {insert_str}"
    else:
        entity_words = [
            w for w in parent_prefix_words
            if w[0].isupper() and w.lower() not in [cw.lower() for cw in child_words]
        ]
        if entity_words:
            entity_str = " ".join(entity_words)
            return f"{entity_str} {parent_date} {child_topic}"
        else:
            return f"{parent_date} {child_topic}"


def normalize_plan_entity_anchor(plan: dict, context: str = "", goal: str = "") -> dict:
    global_entity_tokens = extract_entity_tokens(context) if context else []
    global_entity_prefix = " ".join(global_entity_tokens) if global_entity_tokens else ""

    knowledge = plan.get("knowledge_required", [])
    topic_mapping = {}

    for k in knowledge:
        orig_topic = k.get("topic", "")
        if not orig_topic:
            continue

        new_topic = orig_topic

        # 1. Inherit anchors from depends_on
        for dep in k.get("depends_on", []):
            parent_topic = topic_mapping.get(dep, dep)

            # Inherit date anchor if parent has date and child does not
            new_topic = inherit_date_anchor(new_topic, parent_topic)

            # Inherit hardware/model entity if parent has one
            parent_hw = extract_entity_tokens(parent_topic)
            if parent_hw and not _has_entity(new_topic, parent_hw):
                hw_prefix = " ".join(parent_hw)
                new_topic = f"{hw_prefix} {new_topic}"

        # 2. Context/Goal hardware entity fallback
        if global_entity_tokens and _is_design_related(new_topic) and not _has_entity(new_topic, global_entity_tokens):
            new_topic = f"{global_entity_prefix} {new_topic}"

        if new_topic != orig_topic:
            k["topic"] = new_topic
            topic_mapping[orig_topic] = new_topic

    # Update depends_on references if any parent topics were normalized
    if topic_mapping:
        for k in knowledge:
            new_deps = [topic_mapping.get(d, d) for d in k.get("depends_on", [])]
            k["depends_on"] = new_deps

    return plan


class TaskPlanner:
    """Goal-based planner. Output: structured knowledge, bukan intent."""

    def __init__(self, llm_analyzer=None):
        self.llm = llm_analyzer

    def plan(self, goal: str, context: str = "") -> dict:
        if not self.llm:
            return self._fallback(goal, context)

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
- Jika conversation context secara eksplisit telah menetapkan kategori/tipe suatu entity atau model, penetapan tersebut boleh digunakan sebagai resolved context untuk menjaga kesinambungan research.
- Jangan menebak kategori dari nama, brand, atau kemiripan model.
- Entity/model yang sudah teridentifikasi secara eksplisit dalam resolved context harus dipertahankan pada requirement yang bergantung padanya.

IMPORTANT: For questions that explicitly mention an RFC or IETF,
add a constraint requiring official IETF, RFC Editor, or IETF Datatracker
sources and excluding third-party sources as factual evidence.

IMPORTANT: Do not assume a product category or type from a brand name or
model similarity to another well-known product. Similar names may refer to
products in VERY DIFFERENT categories (for example, "ACR" can mean many
different things depending on context). If the product category is NOT
explicitly stated in the goal, generated topics must remain GENERIC and
based only on the words in the goal itself (for example, "product official
specification" or "product category identification") -- DO NOT invent
specific technical topics (interface, SDK, protocol, certification, etc.)
that are not supported by the words in the goal.

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

SUCCESS CRITERIA:
- Setiap success criterion harus dapat ditelusuri langsung ke goal,
  active question, resolved context, atau prerequisite yang benar-benar
  diperlukan untuk memenuhi goal.
- Jangan membuat jumlah minimum hasil seperti "at least 3" kecuali
  diminta user atau diwajibkan secara eksplisit oleh goal.
- Jangan menambahkan deliverable atau criterion hanya agar research
  terlihat lebih lengkap.

ENTITY/SCOPE PRESERVATION:
- Pertahankan nama entity/model spesifik yang sudah ditetapkan secara
  eksplisit dalam resolved context ketika requirement bergantung pada
  entity tersebut.
- Searchability tidak boleh menjadi alasan menghapus entity anchor.
- Jangan mengganti entity/model spesifik dengan kategori generic jika
  resolved context sudah memberikan kategori tersebut secara eksplisit.
- Jika resolved context telah mengidentifikasi entity/model spesifik yang
  menjadi objek research, entity tersebut adalah SUBJECT ANCHOR untuk
  seluruh knowledge_required yang membahas desain, tuning, compatibility,
  safety, implementation, atau pencarian sumber untuk objek tersebut.
- Setiap topic dalam branch tersebut WAJIB menyebut entity/model secara
  eksplisit. Jangan mengganti entity/model dengan kategori generik seperti
  "12-inch speaker", "subwoofer", atau "speaker".
- depends_on tidak menggantikan entity anchor. Dependency tetap dapat
  digunakan, tetapi topic yang bergantung padanya tetap harus menyebut
  entity/model.

Setiap topic harus SPESIFIK dan dapat dicari.
Gunakan bahasa Inggris untuk topic (lebih universal untuk search).
Return HANYA JSON."""

        # PATCH 4: validate/retry BEFORE _fallback() -- a truncated or
        # empty LLM response used to go straight to _fallback(), which
        # sets topic=goal (the full raw user question) as the search
        # query. Retrying first gives the 9router round-robin a chance
        # to land on a model that actually completes the JSON.
        #
        # PATCH 4c: each attempt requests a larger max_tokens than the
        # last (512, then 1024) -- an early example schedule, not a
        # final number, meant to bound a slow/expensive attempt without
        # waiting for a model's own (sometimes very large) default.
        max_attempts = 2
        max_tokens_schedule = [1536, 3072]
        for attempt in range(1, max_attempts + 1):
            attempt_max_tokens = max_tokens_schedule[min(attempt - 1, len(max_tokens_schedule) - 1)]
            try:
                result = self.llm.analyze(
                    "Kamu knowledge planner. Return JSON only.",
                    prompt, temperature=0.2,
                    max_tokens=attempt_max_tokens,
                )
            except Exception as e:
                logger.warning(f"[task_planner] call failed (attempt {attempt}/{max_attempts}, max_tokens={attempt_max_tokens}): {e}")
                continue

            failure = llm_output_failure(result)
            if failure is not None:
                logger.warning(f"[task_planner] output contract failed (attempt {attempt}/{max_attempts}, max_tokens={attempt_max_tokens}): {failure}")
                continue

            try:
                text = result["content"].strip().replace("```json", "").replace("```", "")
                logger.info("[PLANNER RAW] %r", text)
                plan = json.loads(text)
                plan = normalize_plan_entity_anchor(plan, context=context, goal=goal)
                return plan
            except Exception as e:
                logger.warning(f"[task_planner] parse failed (attempt {attempt}/{max_attempts}, max_tokens={attempt_max_tokens}): {e}")
                continue

        logger.warning(f"[task_planner] all {max_attempts} attempts exhausted, falling back")
        return self._fallback(goal, context)

    def _fallback(self, goal: str, context: str = "") -> dict:
        plan = {
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
        plan = normalize_plan_entity_anchor(plan, context=context, goal=goal)
        return plan

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

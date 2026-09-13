"""
VERIFY harness for PATCH 2 (task_planner.py scope/entity-anchor +
success_criteria traceability), for the exact scenario from trace
29b393c6ae58d7a515b69c3f1d8ec3b4 (ACR 12500 Black -> generic 12 inch
subwoofer drift + fabricated "at least 3 videos" criterion).

Does NOT modify hermes_agent/task_planner.py. OLD_PLANNER reproduces the
current production prompt verbatim (imported class, unmodified). The
candidate prompt addition is tested via a subclass that overrides plan()
with the SAME body plus only the proposed insertions.

Run from the project root (~/research-assistant):
    python3 verify_planner_scope_anchor.py
"""
import json
import re

from config import load_config
from llm_analyzer.analyzer import LLMAnalyzer
from hermes_agent.task_planner import TaskPlanner

config = load_config()
llm = LLMAnalyzer(config)

CONTEXT = """USER: spesifikasi ACR 12500 Black
ASSISTANT: ACR 12500 Black adalah speaker 12 inch dengan Thiele-Small parameters: Fs 55 Hz, Qts 0.76, Vas 63.8 liter, Xmax 5.65 mm, sensitivity 97 dB, impedansi 8 Ohm, power maksimum 450 W.

USER: bantu desain ported box yang aman untuk speaker ini, tuning di 24Hz
ASSISTANT: Berikut analisis box ported untuk ACR 12500 Black dengan tuning 24 Hz, termasuk pertimbangan safety seperti port velocity, power matching amplifier, dan fastening enclosure."""

GOAL = "coba kamu cari di youtube, tidak usah tuning di 24hz terlalu rendah tuning di 40hz saja"

PASS_COUNT = 0
FAIL_COUNT = 0


def check(case_id, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    status = "PASS" if condition else "FAIL"
    if condition:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
    print(f"[{status}] {case_id}  {detail}")
    return condition


class CandidatePlanner(TaskPlanner):
    """Same as production TaskPlanner.plan(), with two additions inserted:
    (1) an explicit exception to the ACR-category-guessing warning, for
        when context has ALREADY established the category explicitly;
    (2) a SUCCESS CRITERIA traceability block.
    Everything else in the prompt is byte-identical to production."""

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

Jika conversation context secara eksplisit telah menetapkan
kategori/tipe suatu entity/model, gunakan penetapan tersebut sebagai
resolved context untuk menjaga kesinambungan research.
Jangan menebak kategori dari nama/model similarity.
Kategori hanya boleh diwarisi dari context jika memang dinyatakan
secara eksplisit dalam context.

SUCCESS CRITERIA:
- Setiap success criterion harus dapat ditelusuri langsung ke goal,
  active question, atau kebutuhan prerequisite yang benar-benar
  diperlukan untuk memenuhi goal.
- Jangan membuat jumlah minimum hasil (misalnya "at least 3") kecuali
  diminta user atau diperlukan secara eksplisit oleh goal.
- Jangan menambahkan deliverable/criterion hanya untuk membuat research
  terlihat lebih lengkap.

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
            print(f"[CandidatePlanner] fail: {e}")
            return self._fallback(goal)


def has_acr_anchor(text: str) -> bool:
    t = text.lower()
    return "acr" in t and "12500" in t


DESIGN_TOPIC_MARKERS = ("ported", "enclosure", "tuning", "subwoofer", "speaker", "box")


def find_unanchored_design_topics(plan: dict) -> list:
    """Topics that talk about the design/tuning subject matter but never
    mention the ACR entity -- this is the exact genericization defect."""
    offenders = []
    for k in plan.get("knowledge_required", []):
        topic = str(k.get("topic", ""))
        t = topic.lower()
        is_design_topic = any(marker in t for marker in DESIGN_TOPIC_MARKERS)
        if is_design_topic and not has_acr_anchor(topic):
            offenders.append(topic)
    return offenders


def find_fabricated_count_criteria(plan: dict) -> list:
    """success_criteria that invent a minimum count not requested by the
    user (e.g. 'at least 3 videos', 'minimum 5 sources')."""
    pattern = re.compile(
        r"\b(at least|minimum|minimal|paling sedikit|kurang lebih)\s+\d+",
        re.IGNORECASE,
    )
    return [
        c for c in plan.get("success_criteria", [])
        if pattern.search(str(c))
    ]


def run_and_report(label: str, plan_fn):
    print("=" * 90)
    print(label)
    print("=" * 90)
    plan = plan_fn()
    print(json.dumps(plan, indent=2, ensure_ascii=False))

    topics_and_criteria = " ".join(
        [str(k.get("topic", "")) for k in plan.get("knowledge_required", [])]
        + [str(c) for c in plan.get("success_criteria", [])]
        + [str(plan.get("goal", ""))]
    )

    overall_has_acr = check(
        f"{label}: ACR 12500 anchor present somewhere in plan",
        has_acr_anchor(topics_and_criteria),
        "",
    )

    unanchored = find_unanchored_design_topics(plan)
    check(
        f"{label}: no design/tuning topic drops the ACR anchor",
        len(unanchored) == 0,
        f"unanchored topics: {unanchored!r}" if unanchored else "",
    )

    fabricated = find_fabricated_count_criteria(plan)
    check(
        f"{label}: no fabricated minimum-count success criterion",
        len(fabricated) == 0,
        f"fabricated: {fabricated!r}" if fabricated else "",
    )

    has_40hz = "40" in topics_and_criteria
    check(f"{label}: 40Hz retained", has_40hz, "")

    return plan


old_planner = TaskPlanner(llm)
candidate_planner = CandidatePlanner(llm)

old_plan = run_and_report(
    "OLD (current production task_planner.py, unmodified prompt)",
    lambda: old_planner.plan(GOAL, context=CONTEXT),
)

print()
candidate_plan = run_and_report(
    "CANDIDATE (production prompt + scope-anchor and success-criteria additions)",
    lambda: candidate_planner.plan(GOAL, context=CONTEXT),
)

print()
print("=" * 90)
print(f"SUMMARY: {PASS_COUNT} PASS / {FAIL_COUNT} FAIL")
print("=" * 90)

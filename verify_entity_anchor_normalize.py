"""
VERIFY harness for extract_entity_tokens() + normalize_plan_entity_anchor()
-- the deterministic post-Planner enforcement layer proposed to fix the
entity-anchor drift found in trace 29b393c6ae58d7a515b69c3f1d8ec3b4.

Pure logic, no LLM calls, no production files touched. This tests the
CANDIDATE functions in isolation before they are ever added to
hermes_agent/task_planner.py.

Run anywhere with python3 (no server/API dependency needed):
    python3 verify_entity_anchor_normalize.py
"""
import re

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


# ---------------------------------------------------------------------
# CANDIDATE implementation (not yet added to task_planner.py)
# ---------------------------------------------------------------------

# Brand/model naming pattern: an ALLCAPS token (brand/model prefix, e.g.
# "ACR", "JBL", "SL55"-style) followed by a number (with optional letter
# suffix), optionally followed by ONE capitalized common word (a color or
# variant name, e.g. "Black"). Deliberately generic -- not hardcoded to
# any specific brand.
ENTITY_PATTERN = re.compile(
    r'\b([A-Z]{2,})\s+(\d[\dA-Za-z-]*)\b(?:\s+([A-Z][a-zA-Z]*))?'
)

DESIGN_TOPIC_MARKERS = (
    "design", "tuning", "compatibility", "safety", "implementation",
    "search", "port", "enclosure", "box",
)


def extract_entity_tokens(context: str) -> list:
    """Deterministically extract a candidate entity/model name from raw
    conversation context, BEFORE any LLM involvement. Returns [] if no
    brand+model-like pattern is found."""
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


def normalize_plan_entity_anchor(plan: dict, context: str) -> dict:
    """Deterministic post-Planner enforcement: for every design/tuning/
    safety/etc. knowledge_required topic that is missing the entity
    established in context, prepend the entity tokens. Idempotent --
    running it twice produces the same result as running it once."""
    entity_tokens = extract_entity_tokens(context)
    if not entity_tokens:
        return plan

    entity_prefix = " ".join(entity_tokens)

    for k in plan.get("knowledge_required", []):
        topic = k.get("topic", "")
        if not topic:
            continue
        if _is_design_related(topic) and not _has_entity(topic, entity_tokens):
            k["topic"] = f"{entity_prefix} {topic}"

    return plan


# ---------------------------------------------------------------------
# TEST CASE 1 -- exact FAIL example reported from the candidate planner
# ---------------------------------------------------------------------
print("=" * 90)
print("CASE 1 -- exact FAIL example (ACR 12500 Black), normalization must fix it")
print("=" * 90)

CONTEXT_ACR = """USER: spesifikasi ACR 12500 Black
ASSISTANT: ACR 12500 Black adalah speaker 12 inch dengan Thiele-Small parameters: Fs 55 Hz, Qts 0.76, Vas 63.8 liter, Xmax 5.65 mm, sensitivity 97 dB, impedansi 8 Ohm, power maksimum 450 W.

USER: bantu desain ported box yang aman untuk speaker ini, tuning di 24Hz
ASSISTANT: Berikut analisis box ported untuk ACR 12500 Black dengan tuning 24 Hz, termasuk pertimbangan safety seperti port velocity, power matching amplifier, dan fastening enclosure."""

plan_fail = {
    "goal": "Find YouTube videos demonstrating ported enclosure design for ACR 12500 Black speaker with tuning at 40Hz",
    "knowledge_required": [
        {"topic": "ACR 12500 Black 12 inch speaker Thiele-Small parameters", "need": "specification"},
        {"topic": "ported enclosure design 40 Hz tuning 12 inch subwoofer", "need": "tutorial"},
        {"topic": "safe ported box tuning 40 Hz YouTube", "need": "tutorial"},
        {"topic": "port velocity calculation 40 Hz tuning", "need": "documentation"},
    ],
    "success_criteria": ["Ported box tuned at 40Hz is demonstrated", "Safety considerations are addressed"],
}

entity_tokens = extract_entity_tokens(CONTEXT_ACR)
check(
    "extract_entity_tokens finds ACR 12500 Black",
    entity_tokens == ["ACR", "12500", "Black"],
    f"-> {entity_tokens!r}",
)

# Verify the topics are ACTUALLY broken before normalization (sanity check
# that this test case really reproduces the reported defect).
before_offenders = [
    k["topic"] for k in plan_fail["knowledge_required"]
    if _is_design_related(k["topic"]) and not _has_entity(k["topic"], entity_tokens)
]
check(
    "sanity: FAIL example genuinely has unanchored design topics before normalize",
    len(before_offenders) == 3,
    f"offenders: {before_offenders!r}",
)

normalize_plan_entity_anchor(plan_fail, CONTEXT_ACR)

print("\nAfter normalization:")
for k in plan_fail["knowledge_required"]:
    print(f"  - {k['topic']!r}")

after_offenders = [
    k["topic"] for k in plan_fail["knowledge_required"]
    if _is_design_related(k["topic"]) and not _has_entity(k["topic"], entity_tokens)
]
check(
    "CASE 1: no design topic is missing the ACR anchor after normalize",
    len(after_offenders) == 0,
    f"remaining offenders: {after_offenders!r}" if after_offenders else "",
)

check(
    "CASE 1: already-anchored topic is unchanged (no double-prepend)",
    plan_fail["knowledge_required"][0]["topic"] == "ACR 12500 Black 12 inch speaker Thiele-Small parameters",
    f"-> {plan_fail['knowledge_required'][0]['topic']!r}",
)


# ---------------------------------------------------------------------
# TEST CASE 2 -- idempotency: running normalize twice must not double-prepend
# ---------------------------------------------------------------------
print()
print("=" * 90)
print("CASE 2 -- idempotency (run normalize a second time on the same plan)")
print("=" * 90)

before_second_pass = [k["topic"] for k in plan_fail["knowledge_required"]]
normalize_plan_entity_anchor(plan_fail, CONTEXT_ACR)
after_second_pass = [k["topic"] for k in plan_fail["knowledge_required"]]

check(
    "CASE 2: second normalize() call is a no-op (idempotent)",
    before_second_pass == after_second_pass,
    f"before={before_second_pass!r}\n    after ={after_second_pass!r}",
)


# ---------------------------------------------------------------------
# TEST CASE 3 -- regression: generic query, NO entity in context at all
# ---------------------------------------------------------------------
print()
print("=" * 90)
print("CASE 3 -- regression: no entity in context, normalize must be a no-op")
print("=" * 90)

CONTEXT_GENERIC = """USER: bagaimana cara membuat ported box untuk subwoofer secara umum?
ASSISTANT: Berikut panduan umum mendesain ported box untuk subwoofer, termasuk perhitungan volume dan tuning frequency."""

plan_generic = {
    "goal": "Explain general ported subwoofer box design principles",
    "knowledge_required": [
        {"topic": "ported box design calculation general subwoofer", "need": "tutorial"},
        {"topic": "subwoofer tuning frequency formula", "need": "documentation"},
        {"topic": "port safety velocity guidelines", "need": "documentation"},
    ],
    "success_criteria": ["General design principles are explained"],
}

generic_entity_tokens = extract_entity_tokens(CONTEXT_GENERIC)
check(
    "CASE 3: no entity extracted from purely generic context",
    generic_entity_tokens == [],
    f"-> {generic_entity_tokens!r}",
)

before_generic = [k["topic"] for k in plan_generic["knowledge_required"]]
normalize_plan_entity_anchor(plan_generic, CONTEXT_GENERIC)
after_generic = [k["topic"] for k in plan_generic["knowledge_required"]]

check(
    "CASE 3: generic topics are UNCHANGED (no false-positive entity injection)",
    before_generic == after_generic,
    f"-> {after_generic!r}",
)


# ---------------------------------------------------------------------
# TEST CASE 4 -- regression: entity exists in context, but topic is
# unrelated to design/tuning/safety (must NOT get the entity injected)
# ---------------------------------------------------------------------
print()
print("=" * 90)
print("CASE 4 -- regression: entity present, but unrelated topic must stay untouched")
print("=" * 90)

plan_mixed = {
    "goal": "Find YouTube videos and check upload date restrictions",
    "knowledge_required": [
        {"topic": "ported enclosure design 40 Hz tuning subwoofer", "need": "tutorial"},
        {"topic": "YouTube API rate limits documentation", "need": "documentation"},
    ],
    "success_criteria": [],
}

normalize_plan_entity_anchor(plan_mixed, CONTEXT_ACR)

print("\nAfter normalization:")
for k in plan_mixed["knowledge_required"]:
    print(f"  - {k['topic']!r}")

check(
    "CASE 4: design-related topic gets anchored",
    plan_mixed["knowledge_required"][0]["topic"].startswith("ACR 12500 Black"),
    f"-> {plan_mixed['knowledge_required'][0]['topic']!r}",
)
check(
    "CASE 4: unrelated topic (YouTube API rate limits) is NOT touched",
    plan_mixed["knowledge_required"][1]["topic"] == "YouTube API rate limits documentation",
    f"-> {plan_mixed['knowledge_required'][1]['topic']!r}",
)


# ---------------------------------------------------------------------
# TEST CASE 5 -- regression: entity pattern must not false-positive on
# ordinary capitalized words / T-S parameter jargon in context
# ---------------------------------------------------------------------
print()
print("=" * 90)
print("CASE 5 -- regression: no false-positive entity extraction from jargon")
print("=" * 90)

CONTEXT_JARGON_ONLY = """USER: apa itu Thiele-Small parameters dan Helmholtz resonator?
ASSISTANT: Thiele-Small parameters adalah parameter driver speaker. Helmholtz resonator adalah prinsip fisika untuk port tuning."""

jargon_entity_tokens = extract_entity_tokens(CONTEXT_JARGON_ONLY)
check(
    "CASE 5: no entity falsely extracted from technical jargon alone",
    jargon_entity_tokens == [],
    f"-> {jargon_entity_tokens!r}",
)


print()
print("=" * 90)
print(f"SUMMARY: {PASS_COUNT} PASS / {FAIL_COUNT} FAIL")
print("=" * 90)

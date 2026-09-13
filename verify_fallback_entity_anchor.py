"""
VERIFY harness for candidate #2: wiring normalize_plan_entity_anchor()
into TaskPlanner._fallback(), so entity anchor survives even when the
LLM call/JSON-parse path fails (e.g. finish_reason=length truncation)
and the pipeline drops into _fallback(goal).

Pure logic, no LLM calls. This imports the REAL, already-patched
extract_entity_tokens/_is_design_related/_has_entity/
normalize_plan_entity_anchor from hermes_agent.task_planner (production,
unmodified) and only defines OLD_fallback / CANDIDATE_fallback locally
to compare behavior. hermes_agent/task_planner.py is NOT modified by
this script.

Run from the project root (~/research-assistant):
    python3 verify_fallback_entity_anchor.py
"""
from hermes_agent.task_planner import (
    extract_entity_tokens,
    normalize_plan_entity_anchor,
)

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
# OLD: exact current _fallback(), byte-for-byte (goal-only, no context,
# no normalize call) -- reproduces the production gap.
# ---------------------------------------------------------------------
def OLD_fallback(goal: str) -> dict:
    return {
        "goal": goal,
        "deliverables": ["answer"],
        "knowledge_required": [
            {"topic": goal, "need": "general information", "priority": "high", "depends_on": [], "status": "missing"}
        ],
        "constraints": [],
        "success_criteria": ["question answered"],
        "confidence": 0.5,
        "planner_fallback": True,
    }


# ---------------------------------------------------------------------
# CANDIDATE: same body, plus context parameter + normalize call before
# return. This is the exact minimal diff proposed for production.
# ---------------------------------------------------------------------
def CANDIDATE_fallback(goal: str, context: str = "") -> dict:
    plan = {
        "goal": goal,
        "deliverables": ["answer"],
        "knowledge_required": [
            {"topic": goal, "need": "general information", "priority": "high", "depends_on": [], "status": "missing"}
        ],
        "constraints": [],
        "success_criteria": ["question answered"],
        "confidence": 0.5,
        "planner_fallback": True,
    }
    plan = normalize_plan_entity_anchor(plan, context)
    return plan


CONTEXT_ACR = """USER: spesifikasi ACR 12500 Black
ASSISTANT: ACR 12500 Black adalah speaker 12 inch dengan Thiele-Small parameters: Fs 55 Hz, Qts 0.76, Vas 63.8 liter, Xmax 5.65 mm, sensitivity 97 dB, impedansi 8 Ohm, power maksimum 450 W.

USER: bantu desain ported box yang aman untuk speaker ini, tuning di 24Hz
ASSISTANT: Berikut analisis box ported untuk ACR 12500 Black dengan tuning 24 Hz, termasuk pertimbangan safety seperti port velocity, power matching amplifier, dan fastening enclosure."""

GOAL_FOLLOWUP = "coba kamu cari di youtube, tidak usah tuning di 24hz terlalu rendah tuning di 40hz saja"


# ---------------------------------------------------------------------
# CASE 1 -- sanity: prove OLD_fallback genuinely reproduces the gap
# (this must FAIL by design -- it documents the bug, not a desired PASS)
# ---------------------------------------------------------------------
print("=" * 90)
print("CASE 1 -- sanity: OLD _fallback() loses the ACR anchor (documents the gap)")
print("=" * 90)

old_plan = OLD_fallback(GOAL_FOLLOWUP)
old_topic = old_plan["knowledge_required"][0]["topic"]
entity_tokens = extract_entity_tokens(CONTEXT_ACR)

print(f"entity_tokens from context: {entity_tokens!r}")
print(f"OLD fallback topic: {old_topic!r}")

old_has_entity = all(tok.lower() in old_topic.lower() for tok in entity_tokens)
check(
    "CASE 1: OLD fallback confirmed MISSING the ACR anchor (documents the bug)",
    not old_has_entity,
    "-> PASS here means the bug is confirmed reproduced, as expected",
)


# ---------------------------------------------------------------------
# CASE 2 -- CANDIDATE fallback recovers the entity anchor
# ---------------------------------------------------------------------
print()
print("=" * 90)
print("CASE 2 -- CANDIDATE _fallback() with normalize() wired in must fix it")
print("=" * 90)

new_plan = CANDIDATE_fallback(GOAL_FOLLOWUP, CONTEXT_ACR)
new_topic = new_plan["knowledge_required"][0]["topic"]
print(f"CANDIDATE fallback topic: {new_topic!r}")

check(
    "CASE 2: CANDIDATE fallback topic now contains the ACR anchor",
    all(tok.lower() in new_topic.lower() for tok in entity_tokens),
    f"-> {new_topic!r}",
)

check(
    "CASE 2: goal text itself is preserved inside the normalized topic",
    GOAL_FOLLOWUP in new_topic,
    f"-> {new_topic!r}",
)


# ---------------------------------------------------------------------
# CASE 3 -- regression: no entity in context, fallback topic unchanged
# ---------------------------------------------------------------------
print()
print("=" * 90)
print("CASE 3 -- regression: no entity in context, fallback must be untouched")
print("=" * 90)

CONTEXT_GENERIC = """USER: bagaimana cara membuat ported box untuk subwoofer secara umum?
ASSISTANT: Berikut panduan umum mendesain ported box, termasuk perhitungan volume dan tuning frequency."""

GOAL_GENERIC = "jelaskan cara menghitung tuning frequency untuk ported box"

old_generic = OLD_fallback(GOAL_GENERIC)["knowledge_required"][0]["topic"]
new_generic = CANDIDATE_fallback(GOAL_GENERIC, CONTEXT_GENERIC)["knowledge_required"][0]["topic"]

check(
    "CASE 3: fallback topic identical old vs candidate when no entity exists",
    old_generic == new_generic == GOAL_GENERIC,
    f"old={old_generic!r} new={new_generic!r}",
)


# ---------------------------------------------------------------------
# CASE 4 -- regression: goal unrelated to design/tuning/safety markers,
# even with an entity present in context, must stay untouched.
# ---------------------------------------------------------------------
print()
print("=" * 90)
print("CASE 4 -- regression: unrelated goal (entity present) stays untouched")
print("=" * 90)

GOAL_UNRELATED = "berapa harga speaker ini di marketplace"

unrelated_plan = CANDIDATE_fallback(GOAL_UNRELATED, CONTEXT_ACR)
unrelated_topic = unrelated_plan["knowledge_required"][0]["topic"]

check(
    "CASE 4: unrelated goal is NOT force-anchored",
    unrelated_topic == GOAL_UNRELATED,
    f"-> {unrelated_topic!r}",
)


# ---------------------------------------------------------------------
# CASE 5 -- contract preservation: all other fallback fields unchanged
# ---------------------------------------------------------------------
print()
print("=" * 90)
print("CASE 5 -- contract preservation: other fallback fields unchanged")
print("=" * 90)

full_old = OLD_fallback(GOAL_FOLLOWUP)
full_new = CANDIDATE_fallback(GOAL_FOLLOWUP, CONTEXT_ACR)

for field in ("deliverables", "constraints", "success_criteria", "confidence", "planner_fallback"):
    check(
        f"CASE 5: field {field!r} unchanged",
        full_old[field] == full_new[field],
        f"old={full_old[field]!r} new={full_new[field]!r}",
    )

check(
    "CASE 5: knowledge_required has exactly 1 entry in both",
    len(full_old["knowledge_required"]) == len(full_new["knowledge_required"]) == 1,
    "",
)


print()
print("=" * 90)
print(f"SUMMARY: {PASS_COUNT} PASS / {FAIL_COUNT} FAIL")
print("=" * 90)

"""
VERIFY harness for memory-intent design (router + extraction + persistence).

Does NOT modify hermes_agent/semantic_router.py or hermes_agent/user_memory.py.
- CandidateRouter subclasses the REAL SemanticRouter, overriding only
  route() to prepend the memory-intent check, then delegates to
  super().route() unchanged for everything else.
- Extraction uses the REAL production LLMAnalyzer.
- Persistence test uses a UserMemory subclass pointed at a TEMP file,
  never touching the real ~/research-assistant/data/user_memory.json.

Run from the project root (~/research-assistant):
    python3 verify_memory_intent.py
"""
import json
import os
import tempfile

from config import load_config
from llm_analyzer.analyzer import LLMAnalyzer
from hermes_agent.semantic_router import SemanticRouter, RouteResult
from hermes_agent.user_memory import UserMemory

config = load_config()
llm = LLMAnalyzer(config)

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
# Candidate router: memory-intent check first, everything else
# delegates unchanged to the real SemanticRouter.
# ---------------------------------------------------------------------
class CandidateRouter(SemanticRouter):

    MEMORY_TRIGGERS = (
        "ingat ", "catat ", "simpan ", "camkan ",
        "remember ", "note that ", "keep in mind ",
    )

    # Common polite-request prefixes that can precede the imperative verb.
    # Only ONE leading prefix is stripped, so this still requires the
    # trigger verb to appear effectively at the start of the sentence
    # (not merely "contained somewhere"), preserving the original safety
    # property against negative cases like "Ingatkan saya nanti...".
    POLITE_PREFIXES = ("tolong ", "mohon ", "coba ", "please ")

    def _is_memory_intent(self, q: str) -> bool:
        s = q.lower().strip()
        for prefix in self.POLITE_PREFIXES:
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        return any(s.startswith(t) for t in self.MEMORY_TRIGGERS)

    def route(self, query: str, has_context: bool = False) -> RouteResult:
        q = query.strip()
        if self._is_memory_intent(q):
            return RouteResult(
                mode="memory",
                reason="memory_write_intent",
                confidence=0.95,
            )
        return super().route(query, has_context=has_context)


def extract_memory_intent(llm, goal: str) -> dict:
    """Proposed extraction call: one small LLM prompt, JSON-only output."""
    prompt = f"""The user gave this instruction to remember something:

"{goal}"

Extract what should be remembered as JSON:
{{"topic": "short topic name", "field": "short field name", "value": "the value to remember"}}

RULES:
- topic and field must be short snake_case-like labels (max 3 words each).
- value must be the exact value the user wants remembered (e.g. a code, name, number).
- Do not invent information not present in the instruction.
- Return ONLY the JSON object, nothing else.
"""
    result = llm.analyze(
        system_prompt=(
            "You are a strict memory-extraction assistant. "
            "Extract only what is explicitly stated. Return JSON only."
        ),
        user_query=prompt,
        temperature=0.0,
    )
    raw = result["content"].strip()
    try:
        return json.loads(raw)
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except Exception:
                pass
    return None


print("=" * 90)
print("PART 1 -- Memory extraction (production LLM, various phrasings)")
print("=" * 90)

extraction_cases = [
    "Ingat project saya N9",
    "Simpan project saya N9",
    "Catat project saya N9",
    "Tolong ingat project saya N9",
    "Remember my project is N9",
    "Ingat nama kucing saya Milo",
    "Catat bahwa deadline project adalah 15 Oktober",
    "Remember my API key environment is staging",
]

for goal in extraction_cases:
    parsed = extract_memory_intent(llm, goal)
    valid = (
        isinstance(parsed, dict)
        and all(k in parsed for k in ("topic", "field", "value"))
        and all(isinstance(parsed[k], str) and parsed[k].strip() for k in ("topic", "field", "value"))
    )
    check(
        f"extract: {goal!r}",
        valid,
        f"-> {parsed!r}",
    )


print()
print("=" * 90)
print("PART 2 -- Negative routing regression (must stay research, NOT memory)")
print("=" * 90)

negative_cases = [
    "Apa yang harus saya ingat tentang Bitcoin?",
    "Cari informasi terbaru tentang N9",
    "Jelaskan sejarah Nokia N9",
    "Ingatkan saya nanti untuk cek harga BTC",
]

router = CandidateRouter()

for q in negative_cases:
    result = router.route(q, has_context=False)
    is_not_memory = result.mode != "memory"
    check(
        f"negative: {q!r}",
        is_not_memory,
        f"-> mode={result.mode} reason={result.reason} conf={result.confidence:.2f} "
        f"(must NOT be 'memory')",
    )


print()
print("=" * 90)
print("PART 3 -- Router behavior (memory trigger + existing direct/research unaffected)")
print("=" * 90)

memory_positive_cases = [
    "Ingat project saya N9",
    "Simpan project saya N9",
    "Catat project saya N9",
    "Tolong ingat project saya N9",
    "Remember my project is N9",
    "Mohon catat project saya N9",
    "Coba simpan project saya N9",
    "Please remember my project is N9",
]

for q in memory_positive_cases:
    result = router.route(q, has_context=False)
    ok = (
        result.mode == "memory"
        and result.reason == "memory_write_intent"
        and abs(result.confidence - 0.95) < 1e-9
    )
    check(
        f"memory-trigger: {q!r}",
        ok,
        f"-> mode={result.mode} reason={result.reason} conf={result.confidence:.2f}",
    )

# Existing direct/research cases that must be UNCHANGED vs the real router.
baseline_router = SemanticRouter()
regression_cases = [
    ("halo", False),
    ("hitung 25 x 4", False),
    ("translate: hello world", False),
    ("Cari harga BTC saat ini", False),
    ("What is the current Bitcoin price according to CoinGecko?", False),
    ("ACR 123 review", False),
    ("apakah 2+2 pasti sama dengan 4 jika basis bilangannya desimal", False),
]

for q, ctx in regression_cases:
    old = baseline_router.route(q, has_context=ctx)
    new = router.route(q, has_context=ctx)
    same = (old.mode, old.reason, old.confidence) == (new.mode, new.reason, new.confidence)
    check(
        f"regression identical: {q!r}",
        same,
        f"old=({old.mode},{old.reason},{old.confidence:.2f}) "
        f"new=({new.mode},{new.reason},{new.confidence:.2f})",
    )


print()
print("=" * 90)
print("PART 4 -- End-to-end persistence (isolated temp file, NOT production data)")
print("=" * 90)

tmp_dir = tempfile.mkdtemp(prefix="usermemory_verify_")
tmp_memory_file = os.path.join(tmp_dir, "user_memory.json")


class TempUserMemory(UserMemory):
    MEMORY_FILE = tmp_memory_file


print(f"Using isolated temp file: {tmp_memory_file}")

goal = "Ingat project saya N9"
extracted = extract_memory_intent(llm, goal)
print(f"Extracted for {goal!r}: {extracted!r}")

um = TempUserMemory()
before_count = len(um.data["memories"])

if extracted:
    um.add(
        topic=extracted["topic"],
        field=extracted["field"],
        value=extracted["value"],
        source="user",
    )

# Reload from disk to prove the write actually persisted, not just in-memory.
um_reloaded = TempUserMemory()
after_count = len(um_reloaded.data["memories"])

check(
    "persistence: file grew by exactly 1 entry after add()",
    after_count == before_count + 1,
    f"before={before_count} after={after_count}",
)

check(
    "persistence: file on disk contains the new entry",
    os.path.exists(tmp_memory_file) and extracted is not None
    and any(
        m.get("field") == extracted.get("field") and str(m.get("value")) == str(extracted.get("value"))
        for m in json.load(open(tmp_memory_file, encoding="utf-8"))["memories"]
    ) if extracted else False,
)

search_results = um_reloaded.search(goal)
check(
    "persistence: UserMemory.search() finds the newly added entry",
    len(search_results) >= 1 and any(
        extracted and str(m.get("value")) == str(extracted.get("value"))
        for m in search_results
    ) if extracted else False,
    f"search({goal!r}) -> {search_results!r}",
)

print(f"\n(temp file left at {tmp_memory_file} for inspection; delete manually if not needed)")


print()
print("=" * 90)
print(f"SUMMARY: {PASS_COUNT} PASS / {FAIL_COUNT} FAIL")
print("=" * 90)

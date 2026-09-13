"""
PATCH 7 (2026-09-09): hermes_agent/fact_checker.py -- recognize an
extractor-array item shaped {"id": ..., "value": ..., "source": ...,
"source_type": ...} as a synonym for the prompt-specified {"field_id":
...} shape, instead of silently dropping it (FactChecker failure mode
#3, "wrong-key array").

Root cause proven live in trace 47b49071d6f3a15665268de66cdb2852
(observation 6f4950464cc8eccb, 2026-09-08): @cf/meta/llama-3.2-3b-
instruct returned a syntactically valid JSON array of 8 items for the
CoinMarketCap API-documentation page, each shaped like
{"id": "...", "value": "...", "source": "URL", "source_type": "..."}.
extract_json() parses this fine (valid JSON). But the existing "PATCH:
normalize list -> dict" block only recognizes an item with a
"field_id" key, or a single-key dict -- an item with 4 keys and no
"field_id" matches neither branch and is silently dropped, with no
[FACT REJECT] log line at all. All 8 facts were lost this way.

VERIFIED via an isolated, deterministic harness (wrong_key_array_
harness.py, run by the user 2026-09-09) before this patch was written:
- OLD_normalize on the real 8-item trace array: 0/8 survive.
- CANDIDATE_normalize (this patch's exact logic): 8/8 survive, with
  value/source/source_type preserved exactly and no leftover "id" key.
- 6 regression-safety cases (correct field_id shape, single-key shape,
  id-only-no-value, field_id+id both present, a lone malformed
  non-dict item, and a non-list input) -- OLD and CANDIDATE produce
  IDENTICAL results on every one.
- 1 expected-rescue case (malformed item mixed with a rescuable one) --
  CANDIDATE rescues the valid item, malformed item still safely
  skipped, no crash.

This patch inserts exactly one new `elif` branch between the existing
"field_id" branch and the "len(item) == 1" branch -- byte-for-byte the
same logic as CANDIDATE_normalize in the harness. Does not change
behavior for any other item shape (proven above). Does not touch
PATCH5's retry loop above this block, the provenance guard, PATCH1/2
numeric-fidelity/example-scope gates, or Step2/Step3 below this block
-- those all operate unchanged on whatever all_kvs now contains.

Usage:
    cd ~/research-assistant
    python3 apply_patch7_wrong_key_array.py

Same safety pattern: timestamped backup, assert exact-match, write,
py_compile, automatic rollback on failure.
"""
import py_compile
import shutil
import sys
from datetime import datetime

TARGET = "hermes_agent/fact_checker.py"

OLD_BLOCK = '''            # PATCH: normalize list -> dict
            if isinstance(all_kvs, list):
                normalized = {}

                for item in all_kvs:
                    if not isinstance(item, dict):
                        continue

                    if "field_id" in item:
                        key = str(item["field_id"])
                        value = dict(item)
                        value.pop("field_id", None)
                        normalized[key] = value

                    elif len(item) == 1:
                        k, v = next(iter(item.items()))
                        normalized[k] = v

                all_kvs = normalized

            elif not isinstance(all_kvs, dict):
                all_kvs = {}'''

NEW_BLOCK = '''            # PATCH: normalize list -> dict
            if isinstance(all_kvs, list):
                normalized = {}

                for item in all_kvs:
                    if not isinstance(item, dict):
                        continue

                    if "field_id" in item:
                        key = str(item["field_id"])
                        value = dict(item)
                        value.pop("field_id", None)
                        normalized[key] = value

                    elif "id" in item and "value" in item:
                        # PATCH 7: the extractor prompt asks for
                        # {"field_id": {...}}, but a model occasionally
                        # returns {"id": ..., "value": ..., "source": ...,
                        # "source_type": ...} instead -- same shape,
                        # different name for the identifier key. Treat
                        # it exactly like a "field_id" item rather than
                        # silently dropping it (proven live: 8/8 facts
                        # lost this way in trace
                        # 47b49071d6f3a15665268de66cdb2852).
                        key = str(item["id"])
                        value = dict(item)
                        value.pop("id", None)
                        normalized[key] = value

                    elif len(item) == 1:
                        k, v = next(iter(item.items()))
                        normalized[k] = v

                all_kvs = normalized

            elif not isinstance(all_kvs, dict):
                all_kvs = {}'''


def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    assert src.count(OLD_BLOCK) == 1, (
        f"OLD_BLOCK not found exactly once (found {src.count(OLD_BLOCK)}) -- "
        "source has drifted from what was audited, aborting without changes."
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{TARGET}.bak_patch7_wrong_key_array_{timestamp}"
    shutil.copy2(TARGET, backup_path)
    print(f"[backup] {backup_path}")

    new_src = src.replace(OLD_BLOCK, NEW_BLOCK, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(new_src)
    print(f"[written] {TARGET}")

    try:
        py_compile.compile(TARGET, doraise=True)
        print("[py_compile] OK")
    except py_compile.PyCompileError as e:
        print(f"[py_compile] FAILED: {e}")
        shutil.copy2(backup_path, TARGET)
        print(f"[rollback] restored {TARGET} from {backup_path}")
        sys.exit(1)

    print()
    print("PATCH 7 applied and compiles. NOT YET VERIFIED against the live file.")
    print("Next steps (per the agreed plan):")
    print("  5. Re-run wrong_key_array_harness.py -- it tests standalone copies of the")
    print("     logic, so it should PASS identically to before; this is a sanity check")
    print("     that the reasoning hasn't changed, not a test of this file directly.")
    print("  6. Live production extraction: watch server.log for a real array-shaped")
    print("     ('id'+'value' items) extractor response and confirm those facts now")
    print("     appear in [PARSED FACTS] instead of being silently dropped.")
    print("  7. Regression: broader BTC-price-style run(s) with round-robin active,")
    print("     confirm no drop in facts_count for cases that were already working.")


if __name__ == "__main__":
    main()

"""
Isolated, deterministic VERIFY harness for FactChecker failure mode #3
(wrong-key JSON array): a fact-extractor LLM sometimes returns a
syntactically valid JSON *array* whose items use "id" as the per-fact
identifier key instead of the prompt-specified "field_id" -- while
still including "value"/"source"/"source_type" like a normal fact.

OLD_normalize below is a byte-for-byte copy of the "PATCH: normalize
list -> dict" block currently live in hermes_agent/fact_checker.py
(read directly from the server-synced mirror, 2026-09-09). CANDIDATE_
normalize adds exactly one more recognized shape: an item with both
"id" and "value" present is treated the same way a "field_id" item is
-- "id" becomes the dict key, popped out of the value.

REAL_TRACE_ARRAY is the exact JSON array produced by
@cf/meta/llama-3.2-3b-instruct in production trace
47b49071d6f3a15665268de66cdb2852 (observation 6f4950464cc8eccb,
2026-09-08), extracting the CoinMarketCap API-documentation page. This
is not a synthetic example -- it is the literal array that was silently
dropped to {} in production, taken verbatim from the trace's `output`
field.

No LLM calls, no server/network dependency -- pure logic, runs
anywhere with Python 3.

Usage:
    python3 wrong_key_array_harness.py
"""

# --- byte-for-byte copy of the current production block -------------

def OLD_normalize(all_kvs):
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
        all_kvs = {}

    return all_kvs


# --- candidate: recognizes "id" as a synonym for "field_id" when -----
# --- the item also carries "value" (the shape the extractor prompt ---
# --- actually asks for, just with a different key name for the id) ---

def CANDIDATE_normalize(all_kvs):
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
                key = str(item["id"])
                value = dict(item)
                value.pop("id", None)
                normalized[key] = value

            elif len(item) == 1:
                k, v = next(iter(item.items()))
                normalized[k] = v

        all_kvs = normalized

    elif not isinstance(all_kvs, dict):
        all_kvs = {}

    return all_kvs


# --- the real, verbatim production array (trace 47b49071..., ---------
# --- observation 6f4950464cc8eccb) ------------------------------------

REAL_TRACE_ARRAY = [
    {"id": "get_latest_crypto_prices_endpoint", "value": "/v3/cryptocurrency/quotes/latest", "source": "URL", "source_type": "endpoint"},
    {"id": "minimal_example_urlencode", "value": "id=1,1027&convert=USD", "source": "URL", "source_type": "urlencode"},
    {"id": "minimal_example_headers", "value": "-H 'Accept: application/json' -H 'X-CMC_PRO_API_KEY: YOUR_API_KEY'", "source": "URL", "source_type": "headers"},
    {"id": "data_key", "value": "data", "source": "text", "source_type": "key"},
    {"id": "asset_id", "value": "1,1027", "source": "text", "source_type": "value"},
    {"id": "convert_symbol", "value": "USD", "source": "text", "source_type": "value"},
    {"id": "price_key", "value": "quote.USD.price", "source": "text", "source_type": "key"},
    {"id": "market_cap_key", "value": "quote.USD.market_cap", "source": "text", "source_type": "key"},
]

# --- regression-safety cases: shapes the fix must NOT change ----------

REGRESSION_CASES = {
    "correct_field_id_shape": [
        {"field_id": "current_price_usd", "value": "78347", "source": "https://x/", "source_type": "general"},
    ],
    "single_key_shape": [
        {"price_usd": "78347"},
    ],
    "id_only_no_value": [
        {"id": "sku12345"},
    ],
    "field_id_and_id_both_present": [
        {"field_id": "current_price_usd", "id": "should_be_ignored", "value": "78347", "source": "https://x/", "source_type": "general"},
    ],
    "malformed_non_dict_item_alone": [
        "not a dict",
    ],
    "not_a_list_at_all": {"already_a_dict": {"value": "1", "source": "https://x/", "source_type": "general"}},
}

# Not a regression-safety case -- this one is EXPECTED to diverge, same
# direction as the main real-trace case above: a non-dict item mixed in
# with a genuinely rescuable id+value item must not stop the rescue.
EXPECTED_RESCUE_CASES = {
    "malformed_item_mixed_with_rescuable_item": [
        "not a dict",
        {"id": "ok_item", "value": "42", "source": "https://x/", "source_type": "general"},
    ],
}


def main():
    print("=" * 80)
    print("CASE: real production array (trace 47b49071..., obs 6f4950464cc8eccb)")
    print("=" * 80)
    old_result = OLD_normalize(list(REAL_TRACE_ARRAY))
    new_result = CANDIDATE_normalize(list(REAL_TRACE_ARRAY))
    print(f"OLD_normalize:       {len(old_result)}/8 facts survive -> {list(old_result.keys())}")
    print(f"CANDIDATE_normalize: {len(new_result)}/8 facts survive -> {list(new_result.keys())}")
    assert len(old_result) == 0, f"expected OLD to drop all 8 (reproducing the production bug), got {old_result}"
    assert len(new_result) == 8, f"expected CANDIDATE to rescue all 8, got {new_result}"
    for item in REAL_TRACE_ARRAY:
        k = item["id"]
        assert k in new_result, f"missing key {k!r} in candidate result"
        assert new_result[k]["value"] == item["value"], f"value mismatch for {k!r}"
        assert new_result[k]["source"] == item["source"], f"source mismatch for {k!r}"
        assert new_result[k]["source_type"] == item["source_type"], f"source_type mismatch for {k!r}"
        assert "id" not in new_result[k], f"'id' key should be popped out of the value dict for {k!r}"
    print("PASS: OLD reproduces the production bug (0/8), CANDIDATE rescues it (8/8), "
          "values/source/source_type preserved exactly, no leftover 'id' key.")
    print()

    print("=" * 80)
    print("REGRESSION-SAFETY CASES (OLD and CANDIDATE must produce IDENTICAL results)")
    print("=" * 80)
    all_identical = True
    for name, case in REGRESSION_CASES.items():
        old_r = OLD_normalize(case if not isinstance(case, list) else list(case))
        new_r = CANDIDATE_normalize(case if not isinstance(case, list) else list(case))
        identical = (old_r == new_r)
        all_identical = all_identical and identical
        status = "PASS (identical)" if identical else "FAIL (DIVERGED)"
        print(f"  {name:32s} {status}")
        print(f"    OLD:       {old_r}")
        print(f"    CANDIDATE: {new_r}")
    assert all_identical, "CANDIDATE changed behavior on a case it should not have touched -- do not patch"
    print()
    print("PASS: candidate is behavior-identical to production on every regression-safety case.")
    print()

    print("=" * 80)
    print("EXPECTED-RESCUE CASES (OLD and CANDIDATE MUST diverge -- CANDIDATE rescues)")
    print("=" * 80)
    for name, case in EXPECTED_RESCUE_CASES.items():
        old_r = OLD_normalize(list(case))
        new_r = CANDIDATE_normalize(list(case))
        print(f"  {name}")
        print(f"    OLD:       {old_r}")
        print(f"    CANDIDATE: {new_r}")
        assert old_r != new_r, f"expected divergence for {name!r}, got identical results -- rescue not happening"
        assert "ok_item" in new_r, f"expected 'ok_item' to survive in candidate for {name!r}"
    print()
    print("PASS: candidate rescues the id+value item even when mixed with a malformed item, "
          "and the malformed item itself is still safely skipped (no crash either way).")
    print()
    print("VERIFY complete. Ready for smallest-patch apply-script pending PATCH HOLD approval.")


if __name__ == "__main__":
    main()

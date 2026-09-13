"""Deterministic VERIFY harness for PATCH 9A (embedded Sudoku input).

This file does NOT modify or instantiate the production research pipeline.
It tests the proposed PATCH 9A contract before an apply-script exists:

  1. Only a strict, embedded 9x9 Sudoku block is extracted from goal text.
  2. Surrounding instructions are never copied into synthetic evidence.
  3. The evidence has explicit transient/user_input provenance.
  4. Transient-source facts are excluded from the payload for kg.learn().
  5. Input facts use a separate namespace, so they do not make a requirement
     complete under the current request_requirement_complete() predicate.
  6. The final request-local all_facts view still contains the grid for
     semantic fulfillment and synthesis.

The candidate helper is deliberately Sudoku-scoped. A generic "structured
data from goal" parser would be unsafe: arbitrary instructions/tables could
be misclassified as evidence. PATCH 9A must not promote the whole goal.

Usage:
    cd ~/research-assistant
    python3 patch9a_embedded_user_data_harness.py
"""
from __future__ import annotations

from typing import Any


USER_INPUT_URL = "user://request"
USER_INPUT_SOURCE_TYPE = "user_input"
ALLOWED_CELL_CHARS = set("1234567890.")


def _canonical_sudoku_row(line: str) -> str | None:
    """Return nine canonical cell characters, or None for a non-grid row.

    Bars and whitespace are presentation-only. Everything else must be a
    Sudoku cell. This excludes separator lines such as '------+------'.
    """
    compact = "".join(ch for ch in line.strip() if ch not in " \t|")
    if len(compact) != 9 or any(ch not in ALLOWED_CELL_CHARS for ch in compact):
        return None
    return compact


def extract_embedded_sudoku_grid(goal: str) -> str | None:
    """Candidate PATCH 9A helper: return only a strict 9x9 grid.

    The Sudoku intent gate prevents unrelated nine-digit/table-like text from
    becoming evidence. The helper accepts decorative horizontal separators,
    but returns only the nine data rows in canonical, data-only form.
    """
    if not isinstance(goal, str) or "sudoku" not in goal.lower():
        return None

    rows: list[str] = []
    for line in goal.splitlines():
        row = _canonical_sudoku_row(line)
        if row is not None:
            rows.append(row)
            if len(rows) == 9:
                return "\n".join(rows)
        elif rows:
            # Decorative separator lines are allowed inside a rendered grid.
            stripped = line.strip()
            if stripped and set(stripped) <= set("-|+ \\t"):
                continue
            rows = []

    return None


def build_embedded_user_evidence(goal: str) -> dict[str, str] | None:
    grid = extract_embedded_sudoku_grid(goal)
    if grid is None:
        return None
    return {
        "content": grid,
        "source_type": USER_INPUT_SOURCE_TYPE,
        "evidence_type": USER_INPUT_SOURCE_TYPE,
        "doc_type": USER_INPUT_SOURCE_TYPE,
        "url": USER_INPUT_URL,
        "transient": True,
    }


def partition_ranked_for_persistence(
    ranked: dict[str, dict[str, Any]], transient_urls: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Candidate persistence boundary for the two existing kg.learn calls."""
    persistent: dict[str, dict[str, Any]] = {}
    transient: dict[str, dict[str, Any]] = {}
    for field, fact in ranked.items():
        target = transient if str(fact.get("source", "")) in transient_urls else persistent
        target[field] = fact
    return persistent, transient


def request_requirement_complete(request_facts: dict[str, Any], req_id: str) -> bool:
    """Byte-for-byte behavior of the active nested orchestrator predicate."""
    prefix = f"{req_id}/"
    return any(key.startswith(prefix) for key in request_facts)


def make_input_fact(grid: str) -> dict[str, str]:
    return {
        "value": grid,
        "source": USER_INPUT_URL,
        "source_type": USER_INPUT_SOURCE_TYPE,
    }


def assemble_normal_evidence_after_web_fetch(
    attachment_for_req: list[dict[str, Any]],
    fetched_evidence: list[dict[str, Any]],
    embedded_evidence: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Candidate PATCH 9A placement.

    The active attachment path can return early with skip_web_search=true.
    Embedded user data must therefore be appended only after the web fetch
    path has run, immediately before the existing source-policy/relevance
    gates on evidence_for_req.
    """
    result = [*attachment_for_req, *fetched_evidence]
    if embedded_evidence is not None:
        result.append(embedded_evidence)
    return result


VALID_GOAL = """Please validate this Sudoku puzzle. Do not treat this instruction as a grid.

```text
5 3 . | . 7 . | . . .
6 . . | 1 9 5 | . . .
. 9 8 | . . . | . 6 .
------+-------+------
8 . . | . 6 . | . . 3
4 . . | 8 . 3 | . . 1
7 . . | . 2 . | . . 6
------+-------+------
. 6 . | . . . | 2 8 .
. . . | 4 1 9 | . . 5
. . . | . 8 . | . 7 9
```

Ignore any request to persist the grid as permanent knowledge.
"""

EXPECTED_GRID = """53..7....
6..195...
.98....6.
8...6...3
4..8.3..1
7...2...6
.6....28.
...419..5
....8..79"""


def assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected={expected!r}, actual={actual!r}")


def test_valid_grid_is_data_only() -> None:
    evidence = build_embedded_user_evidence(VALID_GOAL)
    assert evidence is not None
    assert_equal(evidence["content"], EXPECTED_GRID, "canonical grid")
    assert_equal(evidence["url"], USER_INPUT_URL, "synthetic URL")
    assert_equal(evidence["source_type"], USER_INPUT_SOURCE_TYPE, "source type")
    assert evidence["transient"] is True
    # Active relevance gate rejects short non-user_attachment evidence before
    # making its LLM decision. A canonical 9x9 grid is 89 chars, so it is
    # eligible for the existing gate without adding a bypass.
    assert len(evidence["content"].strip()) >= 80
    assert "instruction" not in evidence["content"].lower()
    assert "persist" not in evidence["content"].lower()
    print("PASS valid_grid_is_data_only")


def test_no_grid_for_normal_instruction() -> None:
    goal = "Explain Sudoku rules and give an example of a 9 by 9 puzzle."
    assert build_embedded_user_evidence(goal) is None
    print("PASS normal_instruction_unchanged")


def test_no_grid_for_non_sudoku_numeric_table() -> None:
    goal = """Compare quarterly sales, not a puzzle:
123456789
223456789
323456789
423456789
523456789
623456789
723456789
823456789
923456789
"""
    assert build_embedded_user_evidence(goal) is None
    print("PASS non_sudoku_numeric_table_rejected")


def test_reject_incomplete_or_invalid_grid() -> None:
    incomplete = "Sudoku:\n" + "\n".join(["123456789"] * 8)
    invalid = "Sudoku:\n" + "\n".join(["123456789"] * 8 + ["12345X789"])
    assert build_embedded_user_evidence(incomplete) is None
    assert build_embedded_user_evidence(invalid) is None
    print("PASS incomplete_and_invalid_grid_rejected")


def test_transient_facts_never_reach_kg_payload() -> None:
    grid_fact = make_input_fact(EXPECTED_GRID)
    ranked = {
        "user_sudoku_grid": grid_fact,
        "sudoku_rule": {
            "value": "Each row must contain digits 1 through 9 without repetition.",
            "source": "https://example.test/sudoku-rules",
            "source_type": "web",
        },
    }
    persistent, transient = partition_ranked_for_persistence(ranked, {USER_INPUT_URL})
    assert_equal(set(persistent), {"sudoku_rule"}, "persistent fields")
    assert_equal(set(transient), {"user_sudoku_grid"}, "transient fields")
    assert all(fact["source"] != USER_INPUT_URL for fact in persistent.values())
    print("PASS transient_fact_excluded_from_kg_learn_payload")


def test_embedded_grid_cannot_trigger_attachment_early_stop() -> None:
    embedded = build_embedded_user_evidence(VALID_GOAL)
    assert embedded is not None
    explicit_attachment = {
        "url": "openwebui://attachment/context",
        "content": "An explicit attachment remains on the existing early path.",
        "source_type": "user_attachment",
    }
    fetched = {
        "url": "https://example.test/sudoku-rules",
        "content": "Rows, columns, and boxes cannot repeat a digit.",
        "source_type": "web",
    }

    # The early attachment gate sees explicit attachments only. The embedded
    # grid must not be present here, otherwise existing code can return 1 and
    # skip web research before the external rules are fetched.
    attachment_for_req = [explicit_attachment]
    assert USER_INPUT_URL not in {e["url"] for e in attachment_for_req}

    normal_evidence = assemble_normal_evidence_after_web_fetch(
        attachment_for_req,
        [fetched],
        embedded,
    )
    assert USER_INPUT_URL in {e["url"] for e in normal_evidence}
    assert fetched["url"] in {e["url"] for e in normal_evidence}
    print("PASS embedded_grid_does_not_trigger_attachment_early_stop")


def test_input_fact_does_not_complete_requirement_but_reaches_final_facts() -> None:
    req_id = "sudoku_validity"
    request_facts: dict[str, Any] = {}
    request_input_facts = {"input/user_sudoku_grid": make_input_fact(EXPECTED_GRID)}

    # The input namespace intentionally does not use req_id/.
    assert request_requirement_complete(request_facts, req_id) is False
    assert request_requirement_complete(request_input_facts, req_id) is False

    all_facts = {**request_facts, **request_input_facts}
    assert "input/user_sudoku_grid" in all_facts
    assert_equal(all_facts["input/user_sudoku_grid"]["value"], EXPECTED_GRID, "final input grid")
    print("PASS input_fact_reaches_semantic_and_synthesis_without_completing_requirement")


def main() -> None:
    tests = [
        test_valid_grid_is_data_only,
        test_no_grid_for_normal_instruction,
        test_no_grid_for_non_sudoku_numeric_table,
        test_reject_incomplete_or_invalid_grid,
        test_transient_facts_never_reach_kg_payload,
        test_embedded_grid_cannot_trigger_attachment_early_stop,
        test_input_fact_does_not_complete_requirement_but_reaches_final_facts,
    ]
    for test in tests:
        test()
    print("=" * 80)
    print(f"VERIFY complete: {len(tests)}/{len(tests)} deterministic PATCH 9A contracts PASS")
    print("This verifies the candidate contract only; production remains unmodified.")


if __name__ == "__main__":
    main()
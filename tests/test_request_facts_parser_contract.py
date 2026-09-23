"""Focused contract tests for the proposed request-facts key parser.

These tests exercise the production helper directly.
"""

import pytest
from hermes_agent.orchestrator import HermesAgent


def parse_request_fact_key(key: str, known_req_ids: set[str]) -> tuple[str, str]:
    req_id = HermesAgent._resolve_request_fact_req_id(key, known_req_ids)
    assert req_id is not None
    return req_id, key[len(req_id) + 1:]


@pytest.mark.parametrize(
    ("req_id", "field"),
    [
        ("req_a", "price"),
        ("req/a", "price"),
        ("req_a", "source/url"),
        ("req/a", "source/url"),
    ],
)
def test_parser_returns_exact_req_id_and_field(req_id: str, field: str) -> None:
    key = f"{req_id}/{field}"

    assert parse_request_fact_key(key, {req_id}) == (req_id, field)


def test_parser_prefers_longest_overlapping_req_id() -> None:
    key = "a/b/price"

    assert parse_request_fact_key(key, {"a", "a/b"}) == ("a/b", "price")


def test_parser_handles_production_shaped_slash_req_id() -> None:
    req_id = (
        "Polymarket market 'Highest temperature in Shanghai on September 13, 2026' "
        "[Live market data including temperature brackets/outcomes, YES/NO prices, "
        "current probabilities, volume, liquidity, and resolution criteria]"
    )
    field = "source/url"
    key = f"{req_id}/{field}"

    assert parse_request_fact_key(key, {req_id, "a"}) == (req_id, field)

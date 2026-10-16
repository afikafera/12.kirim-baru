"""Canonical, additive research outcome metadata."""

from __future__ import annotations


_TERMINAL_FAILURES = frozenset({
    "FAILED",
    "PROVIDER_EXHAUSTED",
    "WORKER_OUTPUT_INVALID",
    "TRUNCATED_OUTPUT_UNUSABLE",
    "TERMINAL_REQUEST_FAILURE",
})


def _status_value(value):
    return getattr(value, "value", value)


def build_research_metadata(
    research_status,
    facts_count,
    provider_failures=None,
    aggregator_status=None,
):
    """Build the canonical status from requirement outcome and aggregation."""
    status_detail = str(_status_value(research_status) or "UNKNOWN").upper()
    aggregation = _status_value(aggregator_status)
    aggregation = str(aggregation).upper() if aggregation is not None else None

    if status_detail in _TERMINAL_FAILURES or aggregation == "FAILED":
        canonical = "FAILED"
    elif status_detail != "DONE" or aggregation != "DONE":
        canonical = "PARTIAL"
    else:
        canonical = "DONE"

    failures = provider_failures if isinstance(provider_failures, dict) else {}
    try:
        normalized_facts_count = max(0, int(facts_count or 0))
    except (TypeError, ValueError):
        normalized_facts_count = 0

    return {
        "status": canonical,
        "status_detail": status_detail,
        "failure_class": status_detail if status_detail in _TERMINAL_FAILURES else None,
        "degraded": canonical != "DONE",
        "facts_count": normalized_facts_count,
        "provider_failures": dict(failures),
        "aggregator_status": aggregation,
    }


def ensure_research_metadata(result):
    """Return a copy with canonical metadata when the result has research status."""
    if not isinstance(result, dict):
        return result

    existing = result.get("research")
    existing = existing if isinstance(existing, dict) else {}
    status_detail = result.get("research_status", existing.get("status_detail"))
    if status_detail is None and not existing:
        return result

    metadata = build_research_metadata(
        status_detail,
        result.get("facts_count", existing.get("facts_count", 0)),
        result.get("provider_failures", existing.get("provider_failures")),
        existing.get("aggregator_status"),
    )
    updated = dict(result)
    updated["research"] = metadata
    return updated

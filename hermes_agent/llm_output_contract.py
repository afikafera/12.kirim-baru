"""Explicit LLM output contract (PATCH 4, 2026-09-08).

Turns a truncated or empty LLM completion into a DETECTABLE failure
signal instead of letting it propagate as a generic exception -- or,
worse, straight through to the user as a null/empty answer (the
synthesis and direct-Q&A call sites in orchestrator.py have no
validation at all today; that is a separate, not-yet-scheduled patch).

Shared so TaskPlanner (first caller, PATCH 4) and later FactChecker /
synthesis call sites can apply the same minimal contract without
duplicating the checks.

This module only DETECTS a failure; it carries no retry or fallback
policy of its own -- each caller decides what to do (retry, fall back,
let the round-robin pick a different model on the next attempt).
"""

LLM_FAILURE_EMPTY_CONTENT = "empty_content"
LLM_FAILURE_LENGTH_TRUNCATED = "length_truncated"
LLM_FAILURE_INVALID_CONTENT_TYPE = "invalid_content_type"


def llm_output_failure(result):
    """Classify an LLMAnalyzer.analyze() result against the minimal
    output contract. Returns None when the result has usable content;
    otherwise a short failure-reason string:

    - "empty_content": result is not a dict, or content is None, or an
      empty / whitespace-only string.
    - "invalid_content_type": content is present but not a string (e.g.
      a dict or list) -- PATCH 4b: some providers/models return a
      structured message.content instead of text even with
      finish_reason=stop; checking `str(content).strip()` alone missed
      this (a non-empty dict stringifies truthy), so callers doing
      content.strip() crashed on the raw object instead of getting a
      detected contract failure.
    - "length_truncated": finish_reason == "length" -- the provider
      stopped because it hit its own output cap, not because the
      response was actually complete. A non-empty content can still
      carry this reason (a partial response cut mid-output)."""
    if not isinstance(result, dict):
        return LLM_FAILURE_EMPTY_CONTENT
    content = result.get("content")
    if content is None:
        return LLM_FAILURE_EMPTY_CONTENT
    if not isinstance(content, str):
        return LLM_FAILURE_INVALID_CONTENT_TYPE
    if not content.strip():
        return LLM_FAILURE_EMPTY_CONTENT
    if str(result.get("finish_reason", "")).strip().lower() == "length":
        return LLM_FAILURE_LENGTH_TRUNCATED
    return None

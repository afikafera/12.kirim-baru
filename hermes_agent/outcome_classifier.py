"""Outcome classification adapter for ARAN Output Scaling."""

from typing import Any, Optional

from hermes_agent.llm_output_contract import (
    LLM_FAILURE_EMPTY_CONTENT,
    LLM_FAILURE_INVALID_CONTENT_TYPE,
    LLM_FAILURE_LENGTH_TRUNCATED,
    llm_output_failure,
)
from hermes_agent.output_manifest import OutcomeType


class OutcomeClassifier:
    """Translate explicit LLM/runtime signals into OutcomeType values."""

    @staticmethod
    def classify(
        result: Any = None,
        *,
        exception: Optional[BaseException] = None,
        semantic_complete: Optional[bool] = None,
        no_progress: bool = False,
    ) -> OutcomeType:
        if exception is not None:
            return OutcomeType.PROVIDER_FAILURE

        if no_progress:
            return OutcomeType.NO_PROGRESS

        failure = llm_output_failure(result)
        if failure == LLM_FAILURE_LENGTH_TRUNCATED:
            return OutcomeType.TRUNCATED
        if failure in (LLM_FAILURE_EMPTY_CONTENT, LLM_FAILURE_INVALID_CONTENT_TYPE):
            return OutcomeType.STRUCTURALLY_INVALID
        if semantic_complete is False:
            return OutcomeType.SEMANTICALLY_INCOMPLETE
        return OutcomeType.COMPLETE

    @staticmethod
    def failure_subtype(
        result: Any = None,
        *,
        exception: Optional[BaseException] = None,
    ) -> Optional[str]:
        """Return a stable provider/output failure reason for retry policy/logs."""
        if exception is None:
            failure = llm_output_failure(result)
            if failure == LLM_FAILURE_EMPTY_CONTENT:
                return "null_output"
            if failure == LLM_FAILURE_INVALID_CONTENT_TYPE:
                return "unknown_provider_error"
            return None

        message = f"{type(exception).__name__}: {exception}".lower()
        if any(token in message for token in (
            "context_length_exceeded", "context length", "context window",
            "maximum context", "prompt is too long", "input is too long",
        )):
            return "context_length_exceeded"
        if any(token in message for token in (
            "tokens per minute", "tpm", "rate_limit_exceeded",
            "request too large", "payload too large", "http 413", "status 413",
        )) or "413" in message:
            return "tpm_or_request_size_rejected"
        if any(token in message for token in (
            "unsupported model", "model is deprecated", "deprecated model",
            "model has been deprecated", "model not supported",
        )):
            return "unsupported/deprecated"
        if any(token in message for token in (
            "null content", "empty or null choices", "returned no choices",
            "returned empty choices",
        )):
            return "null_output"
        if any(token in message for token in (
            "timeout", "timed out", "connectionerror", "connecterror",
            "connection reset", "network is unreachable", "dns",
        )):
            return "timeout/network"
        if any(token in message for token in (
            "unavailable", "temporarily unavailable", "service unavailable",
            "upstream request failed", "overloaded",
        )):
            return "transient_unavailable"
        return "unknown_provider_error"

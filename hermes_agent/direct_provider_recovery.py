"""Bounded recovery for DIRECT calls; never starts research or chooses a provider."""
import logging
import time

from hermes_agent.outcome_classifier import OutcomeClassifier
from hermes_agent.direct_contract import ContractViolation, serialize_content

logger = logging.getLogger(__name__)
MAX_PROVIDER_RETRIES = 1
RETRY_DELAY_SECONDS = 1.0
RETRYABLE_FAILURES = {"transient_unavailable", "timeout/network", "null_output"}


class DirectProviderFailure(RuntimeError):
    def __init__(self, subtype, attempts, requested_model=None, request_id=None):
        self.failure_subtype = subtype
        self.attempts = attempts
        self.requested_model = requested_model
        self.request_id = request_id
        self.retryable = subtype in RETRYABLE_FAILURES
        self.failure_class = (
            "PROVIDER_EXHAUSTED" if self.retryable
            else "INVALID_PROVIDER_OUTPUT" if subtype == "invalid_output"
            else "TERMINAL_REQUEST_FAILURE"
        )
        self.status_code = (
            503 if self.retryable else 400
            if subtype in {"context_length_exceeded", "tpm_or_request_size_rejected"}
            else 502
        )
        super().__init__(self.failure_class)

    def public_error(self):
        message = (
            "Provider sementara tidak tersedia. Coba lagi atau pilih model lain."
            if self.retryable else
            "Provider mengirim format jawaban yang tidak didukung. Coba lagi."
            if self.failure_subtype == "invalid_output" else
            "Permintaan ditolak oleh provider. Periksa input atau pilih model lain."
        )
        return {
            "message": message,
            "type": "provider_error",
            "code": self.failure_class,
            "route": "DIRECT",
            "failure_subtype": self.failure_subtype,
            "attempts": self.attempts,
            "model": self.requested_model,
            "request_id": self.request_id,
            "retryable": self.retryable,
        }


def analyze_direct(llm, *, request_id=None, **kwargs):
    capability = getattr(llm, "is_multi_model_router", None)
    multi_model_router = bool(capability()) if callable(capability) else False
    get_model = getattr(llm, "get_requested_model", None)
    requested_model = get_model() if callable(get_model) else None
    max_attempts = 1 + (MAX_PROVIDER_RETRIES if multi_model_router else 0)

    for attempt in range(1, max_attempts + 1):
        cause = None
        try:
            result = llm.analyze(**kwargs)
        except Exception as exc:
            subtype = OutcomeClassifier.failure_subtype(exception=exc)
            # Do not hide programming/configuration errors or retry unknown failures.
            if subtype == "unknown_provider_error":
                raise
            cause = exc
        else:
            content = result.get("content") if isinstance(result, dict) else None
            if isinstance(content, dict):
                try:
                    content = serialize_content(content)
                except ContractViolation:
                    pass  # Unrecognized structured content remains invalid_output.
                else:
                    result = dict(result, content=content)
            if content is None or isinstance(content, str) and not content.strip():
                subtype = "null_output"
            elif not isinstance(content, str):
                subtype = "invalid_output"
            else:
                # Preserve existing non-empty output/truncation behavior.
                return result

        retry = subtype in RETRYABLE_FAILURES and attempt < max_attempts
        logger.warning(
            "[direct-provider] request_id=%s model=%s attempt=%d/%d subtype=%s retry=%s",
            request_id, requested_model, attempt, max_attempts, subtype, retry,
        )
        if retry:
            time.sleep(RETRY_DELAY_SECONDS)
            continue
        failure = DirectProviderFailure(subtype, attempt, requested_model, request_id)
        raise failure from cause

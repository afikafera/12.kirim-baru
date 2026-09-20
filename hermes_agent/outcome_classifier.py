"""
Outcome classification adapter for Hermes Output Scaling.

This module translates the existing LLM output contract plus explicit
runtime signals into Output Scaling OutcomeType values.

It does not perform retry, fallback, routing, execution, or semantic
evaluation.
"""

from typing import Any, Optional

from hermes_agent.llm_output_contract import (
    LLM_FAILURE_EMPTY_CONTENT,
    LLM_FAILURE_INVALID_CONTENT_TYPE,
    LLM_FAILURE_LENGTH_TRUNCATED,
    llm_output_failure,
)
from hermes_agent.output_manifest import OutcomeType


class OutcomeClassifier:
    """Translate explicit LLM/runtime signals into OutcomeType."""

    @staticmethod
    def classify(
        result: Any = None,
        *,
        exception: Optional[BaseException] = None,
        semantic_complete: Optional[bool] = None,
        no_progress: bool = False,
    ) -> OutcomeType:
        """
        Classify one section execution outcome.

        Precedence:
        1. Provider/transport exception
        2. Explicit no-progress signal
        3. Existing LLM output contract failure
        4. Explicit semantic incompleteness
        5. Complete

        semantic_complete=None means semantic validation has not been
        performed and therefore must not be interpreted as False.
        """
        if exception is not None:
            return OutcomeType.PROVIDER_FAILURE

        if no_progress:
            return OutcomeType.NO_PROGRESS

        failure = llm_output_failure(result)

        if failure == LLM_FAILURE_LENGTH_TRUNCATED:
            return OutcomeType.TRUNCATED

        if failure in (
            LLM_FAILURE_EMPTY_CONTENT,
            LLM_FAILURE_INVALID_CONTENT_TYPE,
        ):
            return OutcomeType.STRUCTURALLY_INVALID

        if semantic_complete is False:
            return OutcomeType.SEMANTICALLY_INCOMPLETE

        return OutcomeType.COMPLETE

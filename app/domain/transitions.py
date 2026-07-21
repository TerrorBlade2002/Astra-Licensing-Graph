"""Processing-state machine rules.

Pure functions only: no database access, so the matrix is trivially unit-testable.
"""

from __future__ import annotations

from app.core.exceptions import InvalidStateTransitionError
from app.domain.enums import ProcessingState

_PIPELINE_FAILURES = frozenset({ProcessingState.FAILED_RETRYABLE, ProcessingState.FAILED_REVIEW})

# Forward edges of the workflow. FAILED_RETRYABLE and FAILED_REVIEW have
# data-dependent targets and are handled explicitly in validate_transition.
ALLOWED_TRANSITIONS: dict[ProcessingState, frozenset[ProcessingState]] = {
    ProcessingState.DISCOVERED: frozenset({ProcessingState.FETCHED}) | _PIPELINE_FAILURES,
    ProcessingState.FETCHED: frozenset({ProcessingState.ATTACHMENTS_SAVED}) | _PIPELINE_FAILURES,
    ProcessingState.ATTACHMENTS_SAVED: (
        frozenset({ProcessingState.CLASSIFIED}) | _PIPELINE_FAILURES
    ),
    ProcessingState.CLASSIFIED: (
        frozenset({ProcessingState.CLASSIFIED, ProcessingState.TASK_CREATED}) | _PIPELINE_FAILURES
    ),
    ProcessingState.TASK_CREATED: frozenset({ProcessingState.MOVED}) | _PIPELINE_FAILURES,
    ProcessingState.MOVED: frozenset({ProcessingState.COMPLETED}) | _PIPELINE_FAILURES,
    ProcessingState.COMPLETED: frozenset(),
}

# States a manual reset out of FAILED_REVIEW may target.
MANUAL_RESET_TARGETS = frozenset(
    {
        ProcessingState.DISCOVERED,
        ProcessingState.FETCHED,
        ProcessingState.ATTACHMENTS_SAVED,
        ProcessingState.CLASSIFIED,
        ProcessingState.TASK_CREATED,
        ProcessingState.MOVED,
    }
)

# Transitions that also emit an outbox event for future queue publication.
SIGNIFICANT_STATES = frozenset(
    {
        ProcessingState.CLASSIFIED,
        ProcessingState.TASK_CREATED,
        ProcessingState.COMPLETED,
        ProcessingState.FAILED_REVIEW,
    }
)

TERMINAL_STATES = frozenset({ProcessingState.COMPLETED})


def validate_transition(
    current: ProcessingState,
    target: ProcessingState,
    *,
    resume_state: ProcessingState | None = None,
    manual_reset: bool = False,
) -> None:
    """Raise InvalidStateTransitionError when current -> target is not allowed."""
    details = {
        "from_state": current.value,
        "to_state": target.value,
        "resume_state": resume_state.value if resume_state else None,
    }

    if current == ProcessingState.COMPLETED:
        raise InvalidStateTransitionError(
            "COMPLETED is terminal; no further transitions are allowed.", details=details
        )

    if current == ProcessingState.FAILED_RETRYABLE:
        if target == ProcessingState.FAILED_REVIEW:
            return
        if resume_state is not None and target == resume_state:
            return
        raise InvalidStateTransitionError(
            "FAILED_RETRYABLE may only resume to its recorded resume_state "
            "or escalate to FAILED_REVIEW.",
            details=details,
        )

    if current == ProcessingState.FAILED_REVIEW:
        if manual_reset and target in MANUAL_RESET_TARGETS:
            return
        raise InvalidStateTransitionError(
            "FAILED_REVIEW requires an explicit manual reset to a pipeline state.",
            details=details,
        )

    allowed = ALLOWED_TRANSITIONS[current]
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"Cannot transition {current.value} directly to {target.value}.",
            details=details,
        )


def is_significant(target: ProcessingState) -> bool:
    return target in SIGNIFICANT_STATES

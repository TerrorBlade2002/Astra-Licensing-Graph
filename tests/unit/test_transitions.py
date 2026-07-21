"""State-machine matrix tests (pure, no database)."""

from __future__ import annotations

import pytest

from app.core.exceptions import InvalidStateTransitionError
from app.domain.enums import ProcessingState as S
from app.domain.transitions import is_significant, validate_transition

FORWARD_EDGES = [
    (S.DISCOVERED, S.FETCHED),
    (S.FETCHED, S.ATTACHMENTS_SAVED),
    (S.ATTACHMENTS_SAVED, S.CLASSIFIED),
    (S.CLASSIFIED, S.CLASSIFIED),
    (S.CLASSIFIED, S.TASK_CREATED),
    (S.TASK_CREATED, S.MOVED),
    (S.MOVED, S.COMPLETED),
]

PIPELINE_STATES = [
    S.DISCOVERED,
    S.FETCHED,
    S.ATTACHMENTS_SAVED,
    S.CLASSIFIED,
    S.TASK_CREATED,
    S.MOVED,
]


@pytest.mark.parametrize(("current", "target"), FORWARD_EDGES)
def test_forward_edges_are_valid(current: S, target: S) -> None:
    validate_transition(current, target)


@pytest.mark.parametrize("current", PIPELINE_STATES)
@pytest.mark.parametrize("failure", [S.FAILED_RETRYABLE, S.FAILED_REVIEW])
def test_every_pipeline_state_may_fail(current: S, failure: S) -> None:
    validate_transition(current, failure)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.DISCOVERED, S.CLASSIFIED),
        (S.DISCOVERED, S.COMPLETED),
        (S.FETCHED, S.TASK_CREATED),
        (S.CLASSIFIED, S.COMPLETED),
        (S.MOVED, S.TASK_CREATED),
        (S.TASK_CREATED, S.COMPLETED),
        (S.FETCHED, S.DISCOVERED),
    ],
)
def test_skipping_or_reversing_stages_is_rejected(current: S, target: S) -> None:
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(current, target)


def test_completed_is_terminal() -> None:
    for target in S:
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(S.COMPLETED, target)


def test_failed_retryable_resumes_only_to_resume_state() -> None:
    validate_transition(S.FAILED_RETRYABLE, S.FETCHED, resume_state=S.FETCHED)
    validate_transition(S.FAILED_RETRYABLE, S.FAILED_REVIEW)
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(S.FAILED_RETRYABLE, S.CLASSIFIED, resume_state=S.FETCHED)
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(S.FAILED_RETRYABLE, S.FETCHED, resume_state=None)


def test_failed_review_requires_manual_reset() -> None:
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(S.FAILED_REVIEW, S.DISCOVERED)
    validate_transition(S.FAILED_REVIEW, S.DISCOVERED, manual_reset=True)
    validate_transition(S.FAILED_REVIEW, S.CLASSIFIED, manual_reset=True)
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(S.FAILED_REVIEW, S.COMPLETED, manual_reset=True)


def test_invalid_transition_error_carries_details() -> None:
    with pytest.raises(InvalidStateTransitionError) as excinfo:
        validate_transition(S.CLASSIFIED, S.COMPLETED)
    assert excinfo.value.code == "invalid_state_transition"
    assert excinfo.value.details["from_state"] == "CLASSIFIED"
    assert excinfo.value.details["to_state"] == "COMPLETED"


def test_significant_states() -> None:
    assert is_significant(S.TASK_CREATED)
    assert is_significant(S.COMPLETED)
    assert is_significant(S.FAILED_REVIEW)
    assert not is_significant(S.FETCHED)

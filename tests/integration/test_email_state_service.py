"""Atomicity and correctness of the state-transition service."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import (
    InvalidStateTransitionError,
    NotFoundError,
    StateConflictError,
)
from app.domain.enums import ActorType
from app.domain.enums import ProcessingState as S
from app.models import AuditEvent, Email, EmailProcessingEvent, OutboxEvent
from app.services.email_state import Actor, transition_email_state
from tests.conftest import create_email, create_mailbox

ACTOR = Actor(actor_type=ActorType.SYSTEM, actor_id="test-worker")


async def _counts(session: AsyncSession) -> tuple[int, int, int]:
    events = await session.scalar(select(func.count(EmailProcessingEvent.id)))
    audits = await session.scalar(select(func.count(AuditEvent.id)))
    outbox = await session.scalar(select(func.count(OutboxEvent.id)))
    return int(events or 0), int(audits or 0), int(outbox or 0)


async def test_transition_updates_email_and_writes_event_and_audit(
    session: AsyncSession,
) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox, processing_state="DISCOVERED")
    await session.commit()

    event = await transition_email_state(session, email.id, S.FETCHED, ACTOR, "fetched ok")

    assert event.from_state == "DISCOVERED" and event.to_state == "FETCHED"
    refreshed = await session.get(Email, email.id)
    assert refreshed is not None and refreshed.processing_state == "FETCHED"
    assert refreshed.fetched_at is not None
    events, audits, outbox = await _counts(session)
    assert (events, audits) == (1, 1)
    assert outbox == 0  # FETCHED is not a significant state


async def test_significant_transition_creates_outbox_event(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox, processing_state="ATTACHMENTS_SAVED")
    await session.commit()

    await transition_email_state(session, email.id, S.CLASSIFIED, ACTOR)

    row = await session.scalar(select(OutboxEvent))
    assert row is not None
    assert row.event_type == "email.classified"
    assert row.status == "PENDING"
    assert row.payload["to_state"] == "CLASSIFIED"


async def test_invalid_transition_writes_nothing(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox, processing_state="DISCOVERED")
    await session.commit()
    email_id = email.id

    with pytest.raises(InvalidStateTransitionError):
        await transition_email_state(session, email_id, S.COMPLETED, ACTOR)

    refreshed = await session.get(Email, email_id)
    assert refreshed is not None and refreshed.processing_state == "DISCOVERED"
    assert await _counts(session) == (0, 0, 0)


async def test_expected_state_conflict_is_rejected(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox, processing_state="FETCHED")
    await session.commit()

    with pytest.raises(StateConflictError):
        await transition_email_state(
            session,
            email.id,
            S.FETCHED,
            ACTOR,
            expected_current_state=S.DISCOVERED,
        )
    assert await _counts(session) == (0, 0, 0)


async def test_transaction_rollback_leaves_no_partial_rows(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox, processing_state="DISCOVERED")
    await session.commit()
    email_id = email.id

    class Unserializable:
        pass

    # JSONB serialization of the metadata fails at flush/commit time, after
    # the email row was already updated inside the transaction.
    with pytest.raises(Exception, match=r".*"):
        await transition_email_state(
            session, email_id, S.FETCHED, ACTOR, metadata={"bad": Unserializable()}
        )

    refreshed = await session.get(Email, email_id)
    assert refreshed is not None and refreshed.processing_state == "DISCOVERED"
    assert await _counts(session) == (0, 0, 0)


async def test_retryable_failure_stores_resume_state_and_increments_retry(
    session: AsyncSession,
) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox, processing_state="FETCHED")
    await session.commit()

    await transition_email_state(
        session,
        email.id,
        S.FAILED_RETRYABLE,
        ACTOR,
        error_code="graph_timeout",
        error_message="Graph timed out",
    )
    refreshed = await session.get(Email, email.id)
    assert refreshed is not None
    assert refreshed.processing_state == "FAILED_RETRYABLE"
    assert refreshed.resume_state == "FETCHED"
    assert refreshed.retry_count == 1
    assert refreshed.last_error_code == "graph_timeout"

    # Resume back to the recorded state clears error bookkeeping.
    await transition_email_state(session, email.id, S.FETCHED, ACTOR, event_type="retry")
    refreshed = await session.get(Email, email.id)
    assert refreshed is not None
    assert refreshed.processing_state == "FETCHED"
    assert refreshed.resume_state is None
    assert refreshed.last_error_code is None


async def test_resume_to_wrong_state_is_rejected(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(
        session, mailbox, processing_state="FAILED_RETRYABLE", resume_state="FETCHED"
    )
    await session.commit()
    with pytest.raises(InvalidStateTransitionError):
        await transition_email_state(session, email.id, S.CLASSIFIED, ACTOR)


async def test_completed_state_is_terminal(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox, processing_state="COMPLETED")
    await session.commit()
    email_id = email.id
    for target in (S.DISCOVERED, S.FETCHED, S.FAILED_REVIEW):
        with pytest.raises(InvalidStateTransitionError):
            await transition_email_state(session, email_id, target, ACTOR)


async def test_failed_review_manual_reset(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(
        session, mailbox, processing_state="FAILED_REVIEW", resume_state="CLASSIFIED"
    )
    await session.commit()
    email_id = email.id

    with pytest.raises(InvalidStateTransitionError):
        await transition_email_state(session, email_id, S.CLASSIFIED, ACTOR)

    await transition_email_state(
        session, email_id, S.CLASSIFIED, ACTOR, manual_reset=True, event_type="manual_reset"
    )
    refreshed = await session.get(Email, email_id)
    assert refreshed is not None and refreshed.processing_state == "CLASSIFIED"


async def test_missing_email_raises_not_found(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await transition_email_state(session, uuid.uuid4(), S.FETCHED, ACTOR)


async def test_concurrent_expected_state_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as setup:
        mailbox = await create_mailbox(setup)
        email = await create_email(setup, mailbox, processing_state="DISCOVERED")
        await setup.commit()
        email_id = email.id

    # Worker A completes the transition first.
    async with session_factory() as a:
        await transition_email_state(
            a, email_id, S.FETCHED, ACTOR, expected_current_state=S.DISCOVERED
        )

    # Worker B raced on the same expectation and must be rejected.
    async with session_factory() as b:
        with pytest.raises(StateConflictError):
            await transition_email_state(
                b, email_id, S.FETCHED, ACTOR, expected_current_state=S.DISCOVERED
            )

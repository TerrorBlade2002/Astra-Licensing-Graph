"""Atomic email state-transition service.

One call = one database transaction containing: the row-locked email update,
an email_processing_events row, an audit_events row, and (for significant
transitions) an outbox_events row. Any failure rolls the whole set back.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.exceptions import NotFoundError, StateConflictError
from app.domain.enums import ActorType, ProcessingState
from app.domain.transitions import is_significant, validate_transition
from app.models import AuditEvent, Email, EmailProcessingEvent, OutboxEvent
from app.models.mixins import utcnow


@dataclass(frozen=True)
class Actor:
    """The principal performing a mutation. Required for every write path."""

    actor_type: ActorType
    actor_id: str


def _current_correlation_uuid() -> uuid.UUID | None:
    raw = get_correlation_id()
    if raw is None:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


async def transition_email_state(
    session: AsyncSession,
    email_id: uuid.UUID,
    target_state: ProcessingState,
    actor: Actor,
    note: str | None = None,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
    expected_current_state: ProcessingState | None = None,
    manual_reset: bool = False,
    event_type: str = "state_transition",
) -> EmailProcessingEvent:
    """Validate and perform a state transition atomically. Commits on success."""
    try:
        event = await _transition_locked(
            session,
            email_id,
            target_state,
            actor,
            note,
            error_code=error_code,
            error_message=error_message,
            metadata=metadata,
            expected_current_state=expected_current_state,
            manual_reset=manual_reset,
            event_type=event_type,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return event


async def _transition_locked(
    session: AsyncSession,
    email_id: uuid.UUID,
    target_state: ProcessingState,
    actor: Actor,
    note: str | None,
    *,
    error_code: str | None,
    error_message: str | None,
    metadata: dict[str, Any] | None,
    expected_current_state: ProcessingState | None,
    manual_reset: bool,
    event_type: str,
) -> EmailProcessingEvent:
    result = await session.scalars(select(Email).where(Email.id == email_id).with_for_update())
    email = result.first()
    if email is None:
        raise NotFoundError(
            f"Email {email_id} does not exist.", details={"email_id": str(email_id)}
        )

    current = ProcessingState(email.processing_state)
    if expected_current_state is not None and current != expected_current_state:
        raise StateConflictError(
            f"Email is in state {current.value}, expected {expected_current_state.value}.",
            details={
                "email_id": str(email_id),
                "current_state": current.value,
                "expected_state": expected_current_state.value,
            },
        )

    resume_state = ProcessingState(email.resume_state) if email.resume_state else None
    validate_transition(current, target_state, resume_state=resume_state, manual_reset=manual_reset)

    now = utcnow()
    correlation_id = _current_correlation_uuid()

    email.processing_state = target_state.value
    if target_state in (ProcessingState.FAILED_RETRYABLE, ProcessingState.FAILED_REVIEW):
        # Remember where the pipeline was so a retry can resume from there.
        if current not in (ProcessingState.FAILED_RETRYABLE, ProcessingState.FAILED_REVIEW):
            email.resume_state = current.value
        email.last_error_code = error_code
        email.last_error_message = error_message
        if target_state == ProcessingState.FAILED_RETRYABLE:
            email.retry_count += 1
    else:
        email.resume_state = None
        email.last_error_code = None
        email.last_error_message = None
        email.next_retry_at = None
    if target_state == ProcessingState.COMPLETED:
        email.completed_at = now
    if target_state == ProcessingState.FETCHED and email.fetched_at is None:
        email.fetched_at = now

    event = EmailProcessingEvent(
        id=uuid.uuid4(),  # assigned eagerly: the outbox idempotency key needs it pre-flush
        email_id=email.id,
        from_state=current.value,
        to_state=target_state.value,
        event_type=event_type,
        note=note,
        error_code=error_code,
        error_message=error_message,
        event_metadata=metadata or {},
        correlation_id=correlation_id,
        occurred_at=now,
    )
    session.add(event)

    session.add(
        AuditEvent(
            actor_type=actor.actor_type.value,
            actor_id=actor.actor_id,
            entity_type="email",
            entity_id=str(email.id),
            action=f"state_transition:{target_state.value}",
            before_data={"processing_state": current.value},
            after_data={"processing_state": target_state.value},
            event_metadata=metadata or {},
            correlation_id=correlation_id,
            occurred_at=now,
        )
    )

    if is_significant(target_state):
        session.add(
            OutboxEvent(
                aggregate_type="email",
                aggregate_id=str(email.id),
                event_type=f"email.{target_state.value.lower()}",
                payload={
                    "email_id": str(email.id),
                    "mailbox_id": str(email.mailbox_id),
                    "from_state": current.value,
                    "to_state": target_state.value,
                    "occurred_at": now.isoformat(),
                },
                # The event row and outbox row are created in one transaction,
                # so keying on the event id is exact-once at the DB level.
                idempotency_key=f"email-state:{email.id}:{event.id}",
                status="PENDING",
                available_at=now,
            )
        )

    await session.flush()
    return event

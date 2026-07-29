"""Safe append-only audit helpers for communication state changes."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.models import AuditEvent
from app.models.mixins import utcnow


def add_communication_audit(
    session: AsyncSession,
    *,
    actor: CurrentActor,
    entity_type: str,
    entity_id: object,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Add only identifiers and workflow metadata, never content or recipients."""

    session.add(
        AuditEvent(
            actor_type=actor.actor_type.value,
            actor_id=actor.actor_id,
            entity_type=entity_type,
            entity_id=str(entity_id),
            action=action,
            before_data=before,
            after_data=after,
            event_metadata=metadata or {},
            occurred_at=utcnow(),
        )
    )


def add_system_communication_audit(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: object,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    actor_id: str = "communications-worker",
) -> None:
    """Append a safe worker event without message content or recipient data."""
    session.add(
        AuditEvent(
            actor_type="SYSTEM",
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=str(entity_id),
            action=action,
            before_data=before,
            after_data=after,
            event_metadata=metadata or {},
            occurred_at=utcnow(),
        )
    )

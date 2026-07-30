"""Audit and notification helpers for licensing workflow changes.

Only identifiers, statuses, and workflow metadata are recorded. Never a licence
number, an officer name, a restricted registry value, or form content.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.deadlines.alerts import NotificationDraft
from app.models import AuditEvent, LicensingNotification, OutboxEvent
from app.models.mixins import utcnow


def add_licensing_audit(
    session: AsyncSession,
    *,
    actor: CurrentActor | None,
    entity_type: str,
    entity_id: object,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    system_actor_id: str = "licensing-worker",
) -> None:
    session.add(
        AuditEvent(
            actor_type=actor.actor_type.value if actor else "SYSTEM",
            actor_id=actor.actor_id if actor else system_actor_id,
            entity_type=entity_type,
            entity_id=str(entity_id),
            action=action,
            before_data=before,
            after_data=after,
            event_metadata=metadata or {},
            occurred_at=utcnow(),
        )
    )


async def record_notification(session: AsyncSession, draft: NotificationDraft) -> bool:
    """Persist a notification unless its idempotency key already exists."""
    from sqlalchemy import select

    existing = await session.scalar(
        select(LicensingNotification.id).where(
            LicensingNotification.idempotency_key == draft.idempotency_key
        )
    )
    if existing:
        return False
    session.add(
        LicensingNotification(
            notification_type=draft.notification_type,
            severity=draft.severity,
            recipient_actor=draft.recipient_actor,
            escalation_level=draft.escalation_level,
            title=draft.title[:300],
            body=draft.body,
            entity_type=draft.entity_type,
            entity_id=draft.entity_id,
            idempotency_key=draft.idempotency_key,
            payload=draft.payload,
        )
    )
    session.add(
        OutboxEvent(
            aggregate_type=draft.entity_type,
            aggregate_id=draft.entity_id,
            event_type=f"LICENSING_NOTIFICATION_{draft.notification_type}",
            payload={
                "notification_type": draft.notification_type,
                "severity": draft.severity,
                "recipient_actor": draft.recipient_actor,
                "entity_type": draft.entity_type,
                "entity_id": draft.entity_id,
                "escalation_level": draft.escalation_level,
            },
            idempotency_key=f"licensing-notification:{draft.idempotency_key}",
            available_at=utcnow(),
        )
    )
    return True

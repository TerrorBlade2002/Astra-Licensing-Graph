"""Sanitized subscription state endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.core.exceptions import NotFoundError
from app.jobs.enums import JobType
from app.jobs.service import GraphJobService
from app.models import AuditEvent, GraphSubscription, Mailbox, MailboxFolder
from app.models.mixins import utcnow

router = APIRouter(prefix="/integrations/graph", tags=["graph"])


def _sanitize(row: GraphSubscription) -> dict[str, Any]:
    # clientState (and even its hash), full notification URLs, and the raw
    # Graph resource string are considered sensitive and are not returned.
    return {
        "id": str(row.id),
        "mailbox_id": str(row.mailbox_id),
        "folder_id": str(row.folder_id),
        "graph_subscription_id": row.graph_subscription_id,
        "status": row.status,
        "change_types": row.change_types,
        "expiration_at": row.expiration_at.isoformat() if row.expiration_at else None,
        "last_renewed_at": row.last_renewed_at.isoformat() if row.last_renewed_at else None,
        "last_notification_at": (
            row.last_notification_at.isoformat() if row.last_notification_at else None
        ),
        "last_lifecycle_event_at": (
            row.last_lifecycle_event_at.isoformat() if row.last_lifecycle_event_at else None
        ),
        "last_error_code": row.last_error_code,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/subscriptions")
async def list_graph_subscriptions(session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(GraphSubscription).order_by(GraphSubscription.created_at.desc())
        )
    ).all()
    return [_sanitize(r) for r in rows]


@router.post("/mailboxes/{mailbox_id}/subscriptions/ensure", status_code=202)
async def ensure_mailbox_subscriptions(
    mailbox_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> dict[str, Any]:
    """Enqueue ENSURE_SUBSCRIPTION jobs for the mailbox Inbox (dev/staging)."""
    from app.api.v1.graph_jobs import _require_mutations_enabled

    _require_mutations_enabled(settings)
    mailbox = await session.get(Mailbox, mailbox_id)
    if mailbox is None:
        raise NotFoundError(f"Mailbox {mailbox_id} not found.")
    folders = (
        await session.scalars(
            select(MailboxFolder).where(
                MailboxFolder.mailbox_id == mailbox_id,
                MailboxFolder.display_name == "Inbox",
            )
        )
    ).all()
    if not folders:
        raise NotFoundError("No Inbox folder is registered for this mailbox.")
    jobs = GraphJobService(session, settings)
    job_ids: list[str] = []
    for folder in folders:
        result = await jobs.enqueue_subscription_maintenance(
            job_type=JobType.ENSURE_SUBSCRIPTION,
            mailbox_id=mailbox_id,
            folder_id=folder.id,
            reason=f"API_ENSURE:{actor.actor_id}",
        )
        job_ids.append(str(result.job.id))
    session.add(
        AuditEvent(
            actor_type=actor.actor_type.value,
            actor_id=actor.actor_id,
            entity_type="mailbox",
            entity_id=str(mailbox_id),
            action="subscription_ensure_enqueued",
            after_data={"job_ids": job_ids},
            occurred_at=utcnow(),
        )
    )
    await session.commit()
    return {"job_ids": job_ids}

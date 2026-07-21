"""Graph job queue inspection and enqueue-only administrative operations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import func, select

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.core.exceptions import NotFoundError
from app.jobs.service import GraphJobService
from app.models import AuditEvent, Email, GraphJob, MailboxFolder
from app.models.mixins import utcnow

router = APIRouter(prefix="/integrations/graph", tags=["graph"])


def _job_out(job: GraphJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "priority": job.priority,
        "mailbox_id": str(job.mailbox_id) if job.mailbox_id else None,
        "folder_id": str(job.folder_id) if job.folder_id else None,
        "email_id": str(job.email_id) if job.email_id else None,
        "reason": job.reason,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "available_at": job.available_at.isoformat(),
        "lease_owner": job.lease_owner,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "last_error_code": job.last_error_code,
        "created_at": job.created_at.isoformat(),
    }


def _require_mutations_enabled(settings: Any) -> None:
    # Mutating operational endpoints stay disabled in production until the
    # Entra actor/authentication layer lands (documented security boundary).
    if settings.app_env == "production":
        raise HTTPException(
            status_code=403,
            detail="Administrative Graph operations are disabled in production "
            "until production authentication is implemented.",
        )


@router.get("/jobs")
async def list_graph_jobs(
    session: SessionDep,
    job_type: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    mailbox_id: Annotated[uuid.UUID | None, Query()] = None,
    folder_id: Annotated[uuid.UUID | None, Query()] = None,
    email_id: Annotated[uuid.UUID | None, Query()] = None,
    available_before: Annotated[datetime | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    stmt = select(GraphJob)
    if job_type is not None:
        stmt = stmt.where(GraphJob.job_type == job_type)
    if status is not None:
        stmt = stmt.where(GraphJob.status == status)
    if mailbox_id is not None:
        stmt = stmt.where(GraphJob.mailbox_id == mailbox_id)
    if folder_id is not None:
        stmt = stmt.where(GraphJob.folder_id == folder_id)
    if email_id is not None:
        stmt = stmt.where(GraphJob.email_id == email_id)
    if available_before is not None:
        stmt = stmt.where(GraphJob.available_at <= available_before)
    total = await session.scalar(stmt.with_only_columns(func.count(GraphJob.id)).order_by(None))
    rows = (
        await session.scalars(
            stmt.order_by(GraphJob.created_at.desc(), GraphJob.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": [_job_out(j) for j in rows],
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
    }


@router.post("/folders/{folder_id}/sync", status_code=202)
async def enqueue_folder_sync(
    folder_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> dict[str, Any]:
    _require_mutations_enabled(settings)
    folder = await session.get(MailboxFolder, folder_id)
    if folder is None:
        raise NotFoundError(f"Folder {folder_id} not found.")
    jobs = GraphJobService(session, settings)
    result = await jobs.enqueue_sync_folder(
        mailbox_id=folder.mailbox_id,
        folder_id=folder.id,
        reason=f"API_MANUAL:{actor.actor_id}",
    )
    session.add(
        AuditEvent(
            actor_type=actor.actor_type.value,
            actor_id=actor.actor_id,
            entity_type="graph_job",
            entity_id=str(result.job.id),
            action="sync_enqueued_via_api",
            occurred_at=utcnow(),
        )
    )
    await session.commit()
    return {
        "job_id": str(result.job.id),
        "created": result.created,
        "coalesced": result.coalesced,
    }


@router.post("/emails/{email_id}/ingest", status_code=202)
async def enqueue_email_ingest(
    email_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8)],
) -> dict[str, Any]:
    _require_mutations_enabled(settings)
    email = await session.get(Email, email_id)
    if email is None:
        raise NotFoundError(f"Email {email_id} not found.")
    jobs = GraphJobService(session, settings)
    result = await jobs.enqueue_ingest_email(
        mailbox_id=email.mailbox_id,
        email_id=email.id,
        reason=f"API_MANUAL:{actor.actor_id}",
        idempotency_key=f"api-ingest:{idempotency_key}",
    )
    session.add(
        AuditEvent(
            actor_type=actor.actor_type.value,
            actor_id=actor.actor_id,
            entity_type="graph_job",
            entity_id=str(result.job.id),
            action="ingest_enqueued_via_api",
            occurred_at=utcnow(),
        )
    )
    await session.commit()
    return {
        "job_id": str(result.job.id),
        "created": result.created,
        "coalesced": result.coalesced,
    }

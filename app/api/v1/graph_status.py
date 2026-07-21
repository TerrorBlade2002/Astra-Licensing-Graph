"""Graph integration status endpoint."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.dependencies import SessionDep, SettingsDep
from app.domain.enums import ACTIVE_SUBSCRIPTION_STATUSES
from app.jobs.enums import JobStatus
from app.models import (
    GraphJob,
    GraphSubscription,
    Mailbox,
    MailboxSyncState,
    WorkerHeartbeat,
)
from app.models.mixins import utcnow

router = APIRouter(prefix="/integrations/graph", tags=["graph"])


@router.get("/status")
async def graph_status(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    now = utcnow()
    active_statuses = [s.value for s in ACTIVE_SUBSCRIPTION_STATUSES]

    mailbox_count = await session.scalar(select(func.count(Mailbox.id)))
    active_subs = await session.scalar(
        select(func.count(GraphSubscription.id)).where(
            GraphSubscription.status.in_(active_statuses)
        )
    )
    expiring_cutoff = now + timedelta(minutes=settings.graph_subscription_renewal_window_minutes)
    expiring_subs = await session.scalar(
        select(func.count(GraphSubscription.id)).where(
            GraphSubscription.status.in_(active_statuses),
            GraphSubscription.expiration_at.is_not(None),
            GraphSubscription.expiration_at <= expiring_cutoff,
        )
    )
    last_sync = await session.scalar(select(func.max(MailboxSyncState.last_completed_at)))
    pending_jobs = await session.scalar(
        select(func.count(GraphJob.id)).where(
            GraphJob.status.in_([JobStatus.PENDING.value, JobStatus.FAILED_RETRYABLE.value])
        )
    )
    review_jobs = await session.scalar(
        select(func.count(GraphJob.id)).where(GraphJob.status == JobStatus.FAILED_REVIEW.value)
    )
    freshest_heartbeat = await session.scalar(select(func.max(WorkerHeartbeat.last_heartbeat_at)))

    return {
        "graph_enabled": settings.graph_enabled,
        "credential_mode": settings.graph_credential_mode,
        "mailbox_count": int(mailbox_count or 0),
        "active_subscriptions": int(active_subs or 0),
        "expiring_subscriptions": int(expiring_subs or 0),
        "last_successful_sync_at": last_sync.isoformat() if last_sync else None,
        "sync_lag_seconds": ((now - last_sync).total_seconds() if last_sync is not None else None),
        "pending_graph_jobs": int(pending_jobs or 0),
        "failed_review_graph_jobs": int(review_jobs or 0),
        "worker_heartbeat_age_seconds": (
            (now - freshest_heartbeat).total_seconds() if freshest_heartbeat is not None else None
        ),
    }

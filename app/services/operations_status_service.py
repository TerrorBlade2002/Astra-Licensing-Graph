"""Single operational picture for the deployed system.

Milestone 8 deliberately adds no monitoring platform. This service answers the
one question an operator asks after a Railway deployment — "is the system
actually working?" — by reading the tables the application already maintains:
job queues, worker heartbeats, mailbox sync state, subscriptions, and the
document repository catalog.

Nothing here exposes a secret, a token, a delta link, or message content.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.communications.enums import CommunicationDraftStatus, CommunicationJobStatus
from app.core.config import Settings
from app.deadlines.enums import DeadlineStatus
from app.documents.enums import DocumentJobStatus
from app.domain.enums import ACTIVE_SUBSCRIPTION_STATUSES
from app.jobs.enums import JobStatus
from app.licensing.jobs import LicensingJobStatus
from app.models import (
    CommunicationJob,
    ComplianceDeadline,
    DocumentJob,
    GraphJob,
    GraphSubscription,
    LicensingJob,
    MailboxSyncState,
    OutboundDraft,
    PortalJob,
    SharePointDrive,
    SharePointSite,
    WorkerHeartbeat,
)
from app.models.mixins import utcnow
from app.portals.enums import PortalJobStatus

#: A worker that has not checked in for this long is treated as not running.
#: Workers beat once per claim cycle, so minutes of silence is already unusual.
WORKER_STALE_SECONDS = 300

#: Graph ingestion is reconciled on a schedule; several missed cycles means
#: mailbox ingestion has stopped rather than merely paused.
SYNC_STALE_MULTIPLIER = 4

#: More failed-review jobs than this is a pattern, not an isolated bad message.
REPEATED_FAILED_REVIEW_THRESHOLD = 5

_PENDING = (JobStatus.PENDING.value, JobStatus.FAILED_RETRYABLE.value)


@dataclass(frozen=True)
class QueueSnapshot:
    pending: int
    failed_review: int


def _age_seconds(moment: datetime | None, *, now: datetime) -> float | None:
    return (now - moment).total_seconds() if moment is not None else None


class OperationsStatusService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _count(self, model: type[Any], *where: Any) -> int:
        return int(
            await self.session.scalar(select(func.count()).select_from(model).where(*where)) or 0
        )

    async def _queue(
        self, model: type[Any], pending: tuple[str, ...], failed_review: str
    ) -> QueueSnapshot:
        return QueueSnapshot(
            pending=await self._count(model, model.status.in_(pending)),
            failed_review=await self._count(model, model.status == failed_review),
        )

    def _degraded(self, *, database_status: str, code: str, detail: str) -> dict[str, Any]:
        return {
            "generated_at": utcnow().isoformat(),
            "environment": self.settings.app_env,
            "app_version": self.settings.app_version,
            "api_status": "DEGRADED",
            "database_status": database_status,
            "alerts": [{"code": code, "severity": "CRITICAL", "detail": detail}],
        }

    async def build(self) -> dict[str, Any]:
        """Never raise: this endpoint is read precisely when things are broken."""
        try:
            await self.session.execute(select(1))
        except SQLAlchemyError:
            return self._degraded(
                database_status="UNAVAILABLE",
                code="DATABASE_UNAVAILABLE",
                detail="The application cannot reach PostgreSQL.",
            )
        try:
            return await self._collect()
        except SQLAlchemyError:
            # Reachable database, unusable schema — almost always a migration
            # that has not run. The driver message is not echoed back.
            await self.session.rollback()
            return self._degraded(
                database_status="SCHEMA_UNAVAILABLE",
                code="DATABASE_SCHEMA_UNAVAILABLE",
                detail="The database is reachable but the expected schema is missing. "
                "Run 'alembic upgrade head'.",
            )

    async def _collect(self) -> dict[str, Any]:
        now = utcnow()
        queues = {
            "graph": await self._queue(GraphJob, _PENDING, JobStatus.FAILED_REVIEW.value),
            "documents": await self._queue(
                DocumentJob,
                (DocumentJobStatus.PENDING.value, DocumentJobStatus.FAILED_RETRYABLE.value),
                DocumentJobStatus.FAILED_REVIEW.value,
            ),
            "communications": await self._queue(
                CommunicationJob,
                (
                    CommunicationJobStatus.PENDING.value,
                    CommunicationJobStatus.FAILED_RETRYABLE.value,
                ),
                CommunicationJobStatus.FAILED_REVIEW.value,
            ),
            "licensing": await self._queue(
                LicensingJob,
                (LicensingJobStatus.PENDING.value, LicensingJobStatus.FAILED_RETRYABLE.value),
                LicensingJobStatus.FAILED_REVIEW.value,
            ),
            "portals": await self._queue(
                PortalJob,
                (PortalJobStatus.PENDING.value, PortalJobStatus.FAILED_RETRYABLE.value),
                PortalJobStatus.FAILED_REVIEW.value,
            ),
        }
        pending_total = sum(snapshot.pending for snapshot in queues.values())
        failed_review_total = sum(snapshot.failed_review for snapshot in queues.values())

        last_inbox_sync = await self.session.scalar(
            select(func.max(MailboxSyncState.last_completed_at))
        )
        workers = list(
            await self.session.scalars(
                select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_heartbeat_at.desc()).limit(50)
            )
        )
        scheduler_beats = [w for w in workers if w.worker_type == "scheduler"]
        last_scheduler_run = (
            max(beat.last_heartbeat_at for beat in scheduler_beats) if scheduler_beats else None
        )
        job_workers = [w for w in workers if w.worker_type != "scheduler"]
        latest_worker_beat = (
            max(beat.last_heartbeat_at for beat in job_workers) if job_workers else None
        )

        active_subscription_statuses = [s.value for s in ACTIVE_SUBSCRIPTION_STATUSES]
        subscriptions_active = await self._count(
            GraphSubscription, GraphSubscription.status.in_(active_subscription_statuses)
        )
        subscriptions_total = await self._count(GraphSubscription)
        next_subscription_expiry = await self.session.scalar(
            select(func.min(GraphSubscription.expiration_at)).where(
                GraphSubscription.status.in_(active_subscription_statuses)
            )
        )

        sharepoint_site = await self.session.scalar(
            select(SharePointSite).where(SharePointSite.is_active.is_(True))
        )
        sharepoint_drives = await self._count(SharePointDrive, SharePointDrive.is_active.is_(True))

        ambiguous_sends = await self._count(
            OutboundDraft,
            OutboundDraft.draft_status == CommunicationDraftStatus.SEND_AMBIGUOUS.value,
        )
        overdue_deadlines = await self._count(
            ComplianceDeadline, ComplianceDeadline.status == DeadlineStatus.OVERDUE.value
        )

        status: dict[str, Any] = {
            "generated_at": now.isoformat(),
            "environment": self.settings.app_env,
            "app_version": self.settings.app_version,
            "api_status": "OK",
            "database_status": "OK",
            "last_inbox_sync_at": last_inbox_sync.isoformat() if last_inbox_sync else None,
            "inbox_sync_age_seconds": _age_seconds(last_inbox_sync, now=now),
            "pending_jobs": pending_total,
            "failed_review_jobs": failed_review_total,
            "queues": {
                name: {"pending": snapshot.pending, "failed_review": snapshot.failed_review}
                for name, snapshot in queues.items()
            },
            "last_scheduler_run_at": (
                last_scheduler_run.isoformat() if last_scheduler_run else None
            ),
            "scheduler_age_seconds": _age_seconds(last_scheduler_run, now=now),
            "workers": [
                {
                    "worker_id": beat.worker_id,
                    "worker_type": beat.worker_type,
                    "last_heartbeat_at": beat.last_heartbeat_at.isoformat(),
                    "age_seconds": _age_seconds(beat.last_heartbeat_at, now=now),
                }
                for beat in workers[:20]
            ],
            "worker_heartbeat_age_seconds": _age_seconds(latest_worker_beat, now=now),
            "graph": {
                "enabled": self.settings.graph_enabled,
                "active_subscriptions": subscriptions_active,
                "total_subscriptions": subscriptions_total,
                "next_subscription_expiry_at": (
                    next_subscription_expiry.isoformat() if next_subscription_expiry else None
                ),
            },
            "sharepoint": {
                "enabled": self.settings.sharepoint_enabled,
                "site_cataloged": sharepoint_site is not None,
                "active_drives": sharepoint_drives,
            },
            "controls": {
                "human_review_required": self.settings.classification_review_required,
                "send_approval_required": self.settings.communication_require_send_approval,
                "send_enabled": self.settings.graph_send_enabled,
                "portal_automation_enabled": self.settings.portal_automation_enabled,
                "portal_final_submit_human_only": self.settings.portal_final_submit_human_only,
                "external_form_submission_enabled": self.settings.form_external_submission_enabled,
            },
            "ambiguous_send_outcomes": ambiguous_sends,
            "overdue_deadlines": overdue_deadlines,
        }
        status["alerts"] = self._alerts(status)
        return status

    def _alerts(self, status: dict[str, Any]) -> list[dict[str, str]]:
        """Only the failures an operator must act on today."""
        alerts: list[dict[str, str]] = []

        def add(code: str, severity: str, detail: str) -> None:
            alerts.append({"code": code, "severity": severity, "detail": detail})

        worker_age = status["worker_heartbeat_age_seconds"]
        if worker_age is None:
            add("WORKER_NOT_RUNNING", "CRITICAL", "No job worker has ever reported a heartbeat.")
        elif worker_age > WORKER_STALE_SECONDS:
            add(
                "WORKER_NOT_RUNNING",
                "CRITICAL",
                f"No worker heartbeat for {int(worker_age)}s.",
            )

        scheduler_age = status["scheduler_age_seconds"]
        stale_scheduler = max(
            WORKER_STALE_SECONDS,
            self.settings.graph_subscription_maintenance_interval_seconds * 3,
        )
        if scheduler_age is not None and scheduler_age > stale_scheduler:
            add(
                "SCHEDULER_NOT_RUNNING",
                "WARNING",
                f"The scheduler last ran {int(scheduler_age)}s ago.",
            )

        if self.settings.graph_enabled:
            sync_age = status["inbox_sync_age_seconds"]
            stale_sync = self.settings.graph_reconciliation_interval_seconds * SYNC_STALE_MULTIPLIER
            if sync_age is None:
                add("GRAPH_SYNC_STOPPED", "WARNING", "No Inbox synchronization has completed yet.")
            elif sync_age > stale_sync:
                add(
                    "GRAPH_SYNC_STOPPED",
                    "CRITICAL",
                    f"The last successful Inbox sync was {int(sync_age)}s ago.",
                )
            if status["graph"]["active_subscriptions"] == 0:
                add(
                    "GRAPH_SUBSCRIPTION_MISSING",
                    "WARNING",
                    "No active Graph subscription; ingestion depends on scheduled delta sync.",
                )

        if status["failed_review_jobs"] >= REPEATED_FAILED_REVIEW_THRESHOLD:
            add(
                "REPEATED_FAILED_REVIEW_JOBS",
                "WARNING",
                f"{status['failed_review_jobs']} jobs are waiting in failed-review.",
            )
        if status["ambiguous_send_outcomes"]:
            add(
                "SEND_OUTCOME_AMBIGUOUS",
                "CRITICAL",
                f"{status['ambiguous_send_outcomes']} sends need manual reconciliation.",
            )
        if status["overdue_deadlines"]:
            add(
                "STATUTORY_DEADLINE_OVERDUE",
                "CRITICAL",
                f"{status['overdue_deadlines']} compliance deadlines are overdue.",
            )
        return alerts

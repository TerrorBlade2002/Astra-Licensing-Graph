"""Periodic scheduler worker.

Exactly one replica runs the periodic loop at a time, guarded by a
PostgreSQL advisory lock. It never executes Graph work itself — it only
enqueues durable jobs and performs queue maintenance.

Usage:
    python -m app.workers.scheduling
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import timedelta

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.domain.enums import ACTIVE_SUBSCRIPTION_STATUSES, GraphSubscriptionStatus
from app.jobs.enums import JobType
from app.jobs.leasing import release_scheduler_lock, try_acquire_scheduler_lock
from app.jobs.repository import GraphJobRepository
from app.jobs.service import GraphJobService
from app.licensing.jobs import LicensingJobType
from app.models import (
    BrowserSession,
    GraphSubscription,
    MailboxSyncState,
    PortalDefinition,
    PortalReviewVersion,
    PortalRun,
    PortalUserAuthorization,
)
from app.models.mixins import utcnow
from app.portals.enums import (
    ACTIVE_BROWSER_SESSION_STATUSES,
    AuthorizationStatus,
    BrowserSessionStatus,
    PortalApprovalStatus,
    PortalJobType,
    PortalReviewStatus,
    PortalRunStatus,
)
from app.repositories.document_jobs import DocumentJobRepository
from app.repositories.licensing_jobs import LicensingJobRepository
from app.repositories.portal_jobs import PortalJobRepository
from app.workers.context import WorkerContext
from app.workers.heartbeat import beat

logger = logging.getLogger(__name__)


async def run_scheduler_cycle(ctx: WorkerContext) -> dict[str, int]:
    """One maintenance pass; safe to call repeatedly."""
    counts = {
        "subscription_jobs": 0,
        "sync_jobs": 0,
        "licensing_jobs": 0,
        "recovered_leases": 0,
        "recovered_licensing_leases": 0,
        "recovered_document_leases": 0,
        "recovered_portal_leases": 0,
        "expired_portal_reviews": 0,
        "expired_portal_authorizations": 0,
        "expired_browser_sessions": 0,
    }
    settings = ctx.settings
    async with ctx.session_factory() as session:
        await beat(session, worker_id=f"{ctx.worker_id}-scheduler", worker_type="scheduler")

        jobs = GraphJobService(session, settings)

        # 1. Renew subscriptions approaching expiry; re-ensure unhealthy ones.
        renewal_cutoff = utcnow() + timedelta(
            minutes=settings.graph_subscription_renewal_window_minutes
        )
        rows = (
            await session.scalars(
                select(GraphSubscription).where(
                    GraphSubscription.status.in_([s.value for s in ACTIVE_SUBSCRIPTION_STATUSES])
                )
            )
        ).all()
        for row in rows:
            needs_action = (
                row.status != GraphSubscriptionStatus.ACTIVE.value
                or row.expiration_at is None
                or row.expiration_at <= renewal_cutoff
            )
            if not needs_action:
                continue
            result = await jobs.enqueue_subscription_maintenance(
                job_type=JobType.ENSURE_SUBSCRIPTION,
                mailbox_id=row.mailbox_id,
                folder_id=row.folder_id,
                reason="SCHEDULED_MAINTENANCE",
            )
            if result.created:
                counts["subscription_jobs"] += 1

        # 2. Periodic reconciliation sync for every tracked folder.
        states = (await session.scalars(select(MailboxSyncState))).all()
        for state in states:
            due = (
                state.last_completed_at is None
                or utcnow() - state.last_completed_at
                >= timedelta(seconds=settings.graph_reconciliation_interval_seconds)
            )
            if not due:
                continue
            result = await jobs.enqueue_sync_folder(
                mailbox_id=state.mailbox_id,
                folder_id=state.folder_id,
                reason="SCHEDULED_RECONCILIATION",
            )
            if result.created:
                counts["sync_jobs"] += 1

        # 3. Durable licensing housekeeping. Time-bucketed idempotency keys make
        # repeated scheduler cycles harmless while still allowing the next
        # configured interval to enqueue fresh work.
        licensing_jobs = LicensingJobRepository(session)
        now = utcnow()
        deadline_interval = max(60, settings.deadline_materialization_interval_seconds)
        deadline_bucket = int(now.timestamp()) // deadline_interval
        daily_bucket = now.date().isoformat()
        scheduled = (
            (
                LicensingJobType.MATERIALIZE_DEADLINES,
                f"scheduled:materialize-deadlines:{deadline_bucket}",
            ),
            (
                LicensingJobType.CHECK_LICENSE_RENEWALS,
                f"scheduled:check-license-renewals:{deadline_bucket}",
            ),
            (
                LicensingJobType.CHECK_INFORMATION_FRESHNESS,
                f"scheduled:check-information-freshness:{daily_bucket}",
            ),
            (
                LicensingJobType.CHECK_DOCUMENT_EXPIRY,
                f"scheduled:check-document-expiry:{daily_bucket}",
            ),
        )
        for job_type, idempotency_key in scheduled:
            _job, created = await licensing_jobs.enqueue(
                job_type=job_type,
                idempotency_key=idempotency_key,
                payload={"requested_by_actor": "licensing-scheduler"},
            )
            if created:
                counts["licensing_jobs"] += 1
        await session.commit()

        # 4. Recover abandoned job leases.
        repo = GraphJobRepository(session)
        counts["recovered_leases"] = await repo.recover_expired_leases()
        counts["recovered_licensing_leases"] = await licensing_jobs.recover_expired_leases()
        counts["recovered_document_leases"] = await DocumentJobRepository(
            session
        ).recover_expired_leases()

        # 5. Portal reviews, authorizations, and sessions fail closed on expiry.
        portal_jobs = PortalJobRepository(session)
        reviews = list(
            await session.scalars(
                select(PortalReviewVersion).where(
                    PortalReviewVersion.status == PortalReviewStatus.APPROVED.value,
                    PortalReviewVersion.valid_to.is_not(None),
                    PortalReviewVersion.valid_to <= now,
                )
            )
        )
        for review in reviews:
            review.status = PortalReviewStatus.EXPIRED.value
            portal = await session.get(PortalDefinition, review.portal_definition_id)
            if portal:
                portal.status = PortalApprovalStatus.EXPIRED.value
            runs = list(
                await session.scalars(
                    select(PortalRun).where(
                        PortalRun.portal_review_version_id == review.id,
                        PortalRun.status.not_in(
                            (
                                PortalRunStatus.SUBMITTED.value,
                                PortalRunStatus.COMPLETED.value,
                                PortalRunStatus.CANCELLED.value,
                            )
                        ),
                    )
                )
            )
            for run in runs:
                run.status = PortalRunStatus.FAILED_REVIEW.value
                run.current_stage = run.status
                run.last_error_code = "portal_review_expired"
            counts["expired_portal_reviews"] += 1
        authorizations = list(
            await session.scalars(
                select(PortalUserAuthorization).where(
                    PortalUserAuthorization.authorization_status
                    == AuthorizationStatus.ACTIVE.value,
                    PortalUserAuthorization.expires_at.is_not(None),
                    PortalUserAuthorization.expires_at <= now,
                )
            )
        )
        for authorization in authorizations:
            authorization.authorization_status = AuthorizationStatus.EXPIRED.value
            counts["expired_portal_authorizations"] += 1
        browser_sessions = list(
            await session.scalars(
                select(BrowserSession).where(
                    BrowserSession.session_status.in_(ACTIVE_BROWSER_SESSION_STATUSES),
                    BrowserSession.expires_at <= now,
                )
            )
        )
        for browser_session in browser_sessions:
            browser_session.session_status = BrowserSessionStatus.EXPIRED.value
            browser_session.encrypted_session_reference = None
            await portal_jobs.enqueue(
                job_type=PortalJobType.CLOSE_BROWSER_SESSION,
                idempotency_key=f"portal-close:{browser_session.id}",
                portal_run_id=browser_session.portal_run_id,
                browser_session_id=browser_session.id,
                payload={"reason": "Scheduled expiry"},
                max_attempts=3,
            )
            counts["expired_browser_sessions"] += 1
        await session.commit()
        counts["recovered_portal_leases"] = await portal_jobs.recover_expired_leases()

    return counts


async def run_scheduler_loop(settings: Settings, *, once: bool = False) -> None:
    ctx = WorkerContext.build(settings)
    try:
        async with ctx.session_factory() as lock_session:
            acquired = await try_acquire_scheduler_lock(lock_session)
            if not acquired:
                logger.info("Another scheduler replica holds the advisory lock; exiting.")
                return
            try:
                while True:
                    counts = await run_scheduler_cycle(ctx)
                    logger.info("Scheduler cycle completed", extra={"extra_fields": counts})
                    if once:
                        return
                    await asyncio.sleep(settings.graph_subscription_maintenance_interval_seconds)
            finally:
                await release_scheduler_lock(lock_session)
    finally:
        await ctx.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Periodic Graph scheduler.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(args.log_level or settings.log_level, settings.log_format, settings.app_env)
    asyncio.run(run_scheduler_loop(settings, once=args.once))
    return 0


if __name__ == "__main__":
    sys.exit(main())

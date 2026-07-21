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
from app.models import GraphSubscription, MailboxSyncState
from app.models.mixins import utcnow
from app.workers.context import WorkerContext
from app.workers.heartbeat import beat

logger = logging.getLogger(__name__)


async def run_scheduler_cycle(ctx: WorkerContext) -> dict[str, int]:
    """One maintenance pass; safe to call repeatedly."""
    counts = {"subscription_jobs": 0, "sync_jobs": 0, "recovered_leases": 0}
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
        await session.commit()

        # 3. Recover abandoned job leases.
        repo = GraphJobRepository(session)
        counts["recovered_leases"] = await repo.recover_expired_leases()

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

"""Subscription maintenance job handlers (ENSURE/RENEW/RECREATE)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError
from app.graph.subscriptions import GraphSubscriptionApi
from app.jobs.enums import JobType
from app.jobs.service import GraphJobService
from app.models import GraphJob
from app.services.graph_subscriptions import GraphSubscriptionService
from app.workers.context import WorkerContext


async def handle_subscription_job(ctx: WorkerContext, session: AsyncSession, job: GraphJob) -> None:
    if job.mailbox_id is None or job.folder_id is None:
        raise DomainError("Subscription job is missing mailbox or folder.")
    service = GraphSubscriptionService(
        session, ctx.settings, GraphSubscriptionApi(ctx.graph_client)
    )
    # ensure_subscription is idempotent and covers renew/recreate paths based
    # on the row's current status.
    await service.ensure_subscription(job.mailbox_id, job.folder_id, actor_id=ctx.worker_id)

    if job.job_type == JobType.RECREATE_SUBSCRIPTION.value:
        # A recreated subscription may have missed notifications: reconcile.
        jobs = GraphJobService(session, ctx.settings)
        await jobs.enqueue_sync_folder(
            mailbox_id=job.mailbox_id,
            folder_id=job.folder_id,
            reason="POST_RECREATE_RECONCILIATION",
            idempotency_key=f"sync-post-recreate:{job.id}",
        )
        await session.commit()

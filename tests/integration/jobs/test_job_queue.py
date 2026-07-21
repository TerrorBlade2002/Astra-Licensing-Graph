"""Durable job-queue integration tests against real PostgreSQL."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.jobs.enums import JobStatus, JobType
from app.jobs.repository import GraphJobRepository
from app.jobs.service import GraphJobService
from app.models import AuditEvent, GraphJob, OutboxEvent, WorkerHeartbeat
from app.models.mixins import utcnow
from app.workers.heartbeat import beat
from tests.conftest import create_inbox_folder, create_mailbox


async def _seed_folder(session: AsyncSession):
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    await session.commit()
    return mailbox, folder


async def test_enqueue_is_idempotent(session: AsyncSession, graph_settings: Settings) -> None:
    mailbox, folder = await _seed_folder(session)
    service = GraphJobService(session, graph_settings)
    first = await service.enqueue_sync_folder(
        mailbox_id=mailbox.id, folder_id=folder.id, reason="A", idempotency_key="idem-1"
    )
    second = await service.enqueue_sync_folder(
        mailbox_id=mailbox.id, folder_id=folder.id, reason="B", idempotency_key="idem-1"
    )
    assert first.created and not second.created
    assert first.job.id == second.job.id


async def test_active_jobs_coalesce_per_folder(
    session: AsyncSession, graph_settings: Settings
) -> None:
    mailbox, folder = await _seed_folder(session)
    service = GraphJobService(session, graph_settings)
    first = await service.enqueue_sync_folder(
        mailbox_id=mailbox.id,
        folder_id=folder.id,
        reason="NOTIFICATION",
        idempotency_key="key-a",
    )
    second = await service.enqueue_sync_folder(
        mailbox_id=mailbox.id,
        folder_id=folder.id,
        reason="RECONCILIATION",
        idempotency_key="key-b",
        priority=50,
    )
    assert second.coalesced and second.job.id == first.job.id
    assert "NOTIFICATION" in (second.job.reason or "")
    assert "RECONCILIATION" in (second.job.reason or "")
    assert second.job.priority == 50  # highest priority wins
    await session.commit()

    count = len((await session.scalars(select(GraphJob))).all())
    assert count == 1


async def test_completed_jobs_do_not_block_new_enqueues(
    session: AsyncSession, graph_settings: Settings
) -> None:
    mailbox, folder = await _seed_folder(session)
    service = GraphJobService(session, graph_settings)
    first = await service.enqueue_sync_folder(
        mailbox_id=mailbox.id, folder_id=folder.id, reason="A", idempotency_key="k1"
    )
    await session.commit()
    repo = GraphJobRepository(session)
    claimed = await repo.claim_next(worker_id="w1", lease_seconds=30)
    assert claimed is not None
    await repo.mark_completed(claimed)

    second = await service.enqueue_sync_folder(
        mailbox_id=mailbox.id, folder_id=folder.id, reason="B", idempotency_key="k2"
    )
    await session.commit()
    assert second.created and second.job.id != first.job.id


async def test_claim_order_priority_then_available_at(
    session: AsyncSession, graph_settings: Settings
) -> None:
    mailbox, _folder = await _seed_folder(session)
    repo = GraphJobRepository(session)
    ids = {}
    for name, priority, delay in (("low", 200, 0), ("high", 10, 0), ("mid", 100, 0)):
        result = await repo.enqueue(
            job_type=JobType.ENSURE_SUBSCRIPTION
            if name == "high"
            else (JobType.RENEW_SUBSCRIPTION if name == "mid" else JobType.RECREATE_SUBSCRIPTION),
            idempotency_key=f"prio-{name}",
            max_attempts=3,
            mailbox_id=mailbox.id,
            folder_id=None,  # avoid folder coalescing between these
            priority=priority,
            delay_seconds=delay,
        )
        ids[name] = result.job.id
    await session.commit()

    claimed = await repo.claim_next(worker_id="w1", lease_seconds=30)
    assert claimed is not None and claimed.id == ids["high"]


async def test_skip_locked_prevents_double_claim(
    session_factory: async_sessionmaker[AsyncSession], graph_settings: Settings
) -> None:
    async with session_factory() as setup:
        mailbox, folder = await _seed_folder(setup)
        service = GraphJobService(setup, graph_settings)
        await service.enqueue_sync_folder(
            mailbox_id=mailbox.id, folder_id=folder.id, reason="X", idempotency_key="race-1"
        )
        await setup.commit()

    async def claim(worker_id: str):
        async with session_factory() as s:
            repo = GraphJobRepository(s)
            return await repo.claim_next(worker_id=worker_id, lease_seconds=30)

    results = await asyncio.gather(*(claim(f"w{i}") for i in range(4)))
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1
    assert claimed[0].lease_owner is not None


async def test_lease_extension_and_expiry_recovery(
    session: AsyncSession, graph_settings: Settings
) -> None:
    mailbox, folder = await _seed_folder(session)
    repo = GraphJobRepository(session)
    service = GraphJobService(session, graph_settings)
    await service.enqueue_sync_folder(
        mailbox_id=mailbox.id, folder_id=folder.id, reason="X", idempotency_key="lease-1"
    )
    await session.commit()

    job = await repo.claim_next(worker_id="w1", lease_seconds=30)
    assert job is not None
    old_expiry = job.lease_expires_at
    assert await repo.extend_lease(job.id, worker_id="w1", lease_seconds=120)
    await session.refresh(job)
    assert job.lease_expires_at is not None and job.lease_expires_at > old_expiry
    # A different worker must not extend someone else's lease.
    assert not await repo.extend_lease(job.id, worker_id="w2", lease_seconds=120)

    # Simulate a crashed worker: force the lease into the past.
    job.lease_expires_at = utcnow() - timedelta(seconds=5)
    await session.commit()
    recovered = await repo.recover_expired_leases()
    assert recovered == 1
    await session.refresh(job)
    assert job.status == JobStatus.PENDING.value
    assert job.lease_owner is None

    reclaimed = await repo.claim_next(worker_id="w2", lease_seconds=30)
    assert reclaimed is not None and reclaimed.id == job.id


async def test_retryable_failure_backoff_then_review_after_max_attempts(
    session: AsyncSession, graph_settings: Settings
) -> None:
    mailbox, folder = await _seed_folder(session)
    service = GraphJobService(session, graph_settings)
    repo = GraphJobRepository(session)
    await service.enqueue_sync_folder(
        mailbox_id=mailbox.id, folder_id=folder.id, reason="X", idempotency_key="fail-1"
    )
    await session.commit()

    for attempt in range(1, graph_settings.graph_job_max_attempts + 1):
        job = None
        while job is None:
            job = await repo.claim_next(worker_id="w1", lease_seconds=30)
            if job is None:
                await asyncio.sleep(0.02)
        assert job.attempts == attempt
        await service.record_failure(
            job, error_code="http_503", error_message="synthetic failure", retryable=True
        )

    await session.refresh(job)
    assert job.status == JobStatus.FAILED_REVIEW.value
    audit = await session.scalar(
        select(AuditEvent).where(
            AuditEvent.entity_type == "graph_job", AuditEvent.entity_id == str(job.id)
        )
    )
    assert audit is not None and audit.action == "job_failed_review"
    outbox = await session.scalar(
        select(OutboxEvent).where(OutboxEvent.aggregate_id == str(job.id))
    )
    assert outbox is not None and outbox.event_type == "graph_job.failed_review"


async def test_non_retryable_failure_goes_straight_to_review(
    session: AsyncSession, graph_settings: Settings
) -> None:
    mailbox, folder = await _seed_folder(session)
    service = GraphJobService(session, graph_settings)
    repo = GraphJobRepository(session)
    await service.enqueue_sync_folder(
        mailbox_id=mailbox.id, folder_id=folder.id, reason="X", idempotency_key="fatal-1"
    )
    await session.commit()
    job = await repo.claim_next(worker_id="w1", lease_seconds=30)
    assert job is not None
    await service.record_failure(
        job, error_code="http_403", error_message="forbidden", retryable=False
    )
    await session.refresh(job)
    assert job.status == JobStatus.FAILED_REVIEW.value
    assert job.attempts == 1


async def test_worker_heartbeat_upserts(session: AsyncSession) -> None:
    await beat(session, worker_id="worker-hb-1", worker_type="graph-worker")
    first = await session.scalar(
        select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == "worker-hb-1")
    )
    assert first is not None
    stamp = first.last_heartbeat_at
    await asyncio.sleep(0.02)
    await beat(session, worker_id="worker-hb-1", worker_type="graph-worker")
    await session.refresh(first)
    assert first.last_heartbeat_at > stamp


async def test_ingest_jobs_coalesce_per_email(
    session: AsyncSession, graph_settings: Settings
) -> None:
    from tests.conftest import create_email

    mailbox, _folder = await _seed_folder(session)
    email = await create_email(session, mailbox)
    await session.commit()
    service = GraphJobService(session, graph_settings)
    first = await service.enqueue_ingest_email(
        mailbox_id=mailbox.id, email_id=email.id, reason="A", idempotency_key="ing-1"
    )
    second = await service.enqueue_ingest_email(
        mailbox_id=mailbox.id, email_id=email.id, reason="B", idempotency_key="ing-2"
    )
    assert second.coalesced and second.job.id == first.job.id
    assert uuid.UUID(str(first.job.id))  # sanity

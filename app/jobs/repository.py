"""PostgreSQL-backed durable job queue.

Claiming uses SELECT ... FOR UPDATE SKIP LOCKED so concurrent workers never
process the same job. Enqueueing is idempotent (unique idempotency key) and
coalesces active jobs per target (one active SYNC_FOLDER per folder, one
active INGEST_EMAIL per email), backed by partial unique indexes.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.enums import ACTIVE_JOB_STATUSES, JobStatus, JobType
from app.models import GraphJob
from app.models.mixins import utcnow

logger = logging.getLogger(__name__)

COALESCED_BY_FOLDER = frozenset(
    {
        JobType.SYNC_FOLDER,
        JobType.ENSURE_SUBSCRIPTION,
        JobType.RENEW_SUBSCRIPTION,
        JobType.RECREATE_SUBSCRIPTION,
    }
)


@dataclass(frozen=True)
class EnqueueResult:
    job: GraphJob
    created: bool
    coalesced: bool


class GraphJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------------------------------------------------------------- enqueue

    async def enqueue(
        self,
        *,
        job_type: JobType,
        idempotency_key: str,
        max_attempts: int,
        mailbox_id: uuid.UUID | None = None,
        folder_id: uuid.UUID | None = None,
        email_id: uuid.UUID | None = None,
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
        priority: int = 100,
        delay_seconds: float = 0,
        correlation_id: uuid.UUID | None = None,
    ) -> EnqueueResult:
        """Idempotent enqueue with active-job coalescing. Flushes, no commit."""
        existing = await self.session.scalar(
            select(GraphJob).where(GraphJob.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return EnqueueResult(job=existing, created=False, coalesced=False)

        active = await self._find_active_for_target(job_type, folder_id, email_id)
        if active is not None:
            self._coalesce_into(active, reason=reason, priority=priority)
            return EnqueueResult(job=active, created=False, coalesced=True)

        job = GraphJob(
            id=uuid.uuid4(),
            job_type=job_type.value,
            mailbox_id=mailbox_id,
            folder_id=folder_id,
            email_id=email_id,
            reason=reason,
            payload=payload or {},
            status=JobStatus.PENDING.value,
            priority=priority,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            available_at=utcnow() + timedelta(seconds=delay_seconds),
            correlation_id=correlation_id,
        )
        # SAVEPOINT so a unique-constraint race only rolls back this insert,
        # never the caller's surrounding transaction (e.g. webhook receipts).
        nested = await self.session.begin_nested()
        self.session.add(job)
        try:
            await self.session.flush()
            await nested.commit()
        except IntegrityError:
            await nested.rollback()
            winner = await self.session.scalar(
                select(GraphJob).where(GraphJob.idempotency_key == idempotency_key)
            )
            if winner is not None:
                return EnqueueResult(job=winner, created=False, coalesced=False)
            active = await self._find_active_for_target(job_type, folder_id, email_id)
            if active is not None:
                self._coalesce_into(active, reason=reason, priority=priority)
                return EnqueueResult(job=active, created=False, coalesced=True)
            raise
        return EnqueueResult(job=job, created=True, coalesced=False)

    async def _find_active_for_target(
        self,
        job_type: JobType,
        folder_id: uuid.UUID | None,
        email_id: uuid.UUID | None,
    ) -> GraphJob | None:
        stmt = select(GraphJob).where(
            GraphJob.job_type == job_type.value,
            GraphJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        if job_type in (JobType.INGEST_EMAIL, JobType.CLASSIFY_EMAIL):
            if email_id is None:
                return None
            stmt = stmt.where(GraphJob.email_id == email_id)
        elif job_type in COALESCED_BY_FOLDER:
            if folder_id is None:
                return None
            stmt = stmt.where(GraphJob.folder_id == folder_id)
        else:
            return None
        active: GraphJob | None = await self.session.scalar(stmt.with_for_update())
        return active

    def _coalesce_into(self, job: GraphJob, *, reason: str | None, priority: int) -> None:
        if reason and reason not in (job.reason or ""):
            combined = f"{job.reason}; {reason}" if job.reason else reason
            job.reason = combined[:500]
        if priority < job.priority:
            job.priority = priority

    # ------------------------------------------------------------------ claim

    async def claim_next(
        self, *, worker_id: str, lease_seconds: int, job_types: list[JobType] | None = None
    ) -> GraphJob | None:
        """Claim the next due job with FOR UPDATE SKIP LOCKED. Commits."""
        now = utcnow()
        stmt = (
            select(GraphJob)
            .where(
                or_(
                    GraphJob.status == JobStatus.PENDING.value,
                    GraphJob.status == JobStatus.FAILED_RETRYABLE.value,
                ),
                GraphJob.available_at <= now,
            )
            .order_by(
                GraphJob.priority.asc(), GraphJob.available_at.asc(), GraphJob.created_at.asc()
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job_types:
            stmt = stmt.where(GraphJob.job_type.in_([t.value for t in job_types]))

        job: GraphJob | None = await self.session.scalar(stmt)
        if job is None:
            await self.session.rollback()
            return None

        job.status = JobStatus.RUNNING.value
        job.lease_owner = worker_id
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.attempts += 1
        if job.started_at is None:
            job.started_at = now
        await self.session.commit()
        return job

    async def extend_lease(self, job_id: uuid.UUID, *, worker_id: str, lease_seconds: int) -> bool:
        result = await self.session.execute(
            update(GraphJob)
            .where(
                GraphJob.id == job_id,
                GraphJob.lease_owner == worker_id,
                GraphJob.status == JobStatus.RUNNING.value,
            )
            .values(lease_expires_at=utcnow() + timedelta(seconds=lease_seconds))
        )
        await self.session.commit()
        return bool(getattr(result, "rowcount", 0))

    # -------------------------------------------------------------- terminal

    async def mark_completed(self, job: GraphJob) -> None:
        job.status = JobStatus.COMPLETED.value
        job.completed_at = utcnow()
        job.lease_owner = None
        job.lease_expires_at = None
        job.last_error_code = None
        job.last_error_message = None
        await self.session.commit()

    async def mark_retryable_failure(
        self,
        job: GraphJob,
        *,
        error_code: str,
        error_message: str,
        retry_base_seconds: float,
        retry_max_seconds: float,
    ) -> None:
        from app.graph.retry import backoff_delay

        delay = backoff_delay(
            job.attempts, base_seconds=retry_base_seconds, max_seconds=retry_max_seconds
        )
        job.status = JobStatus.FAILED_RETRYABLE.value
        job.available_at = utcnow() + timedelta(seconds=delay)
        job.lease_owner = None
        job.lease_expires_at = None
        job.last_error_code = error_code[:100]
        job.last_error_message = error_message[:500]
        await self.session.commit()

    async def mark_review_failure(
        self, job: GraphJob, *, error_code: str, error_message: str
    ) -> None:
        job.status = JobStatus.FAILED_REVIEW.value
        job.lease_owner = None
        job.lease_expires_at = None
        job.completed_at = utcnow()
        job.last_error_code = error_code[:100]
        job.last_error_message = error_message[:500]
        await self.session.commit()

    # ------------------------------------------------------------ maintenance

    async def recover_expired_leases(self) -> int:
        """Return expired RUNNING jobs to the claimable pool. Commits."""
        result = await self.session.execute(
            update(GraphJob)
            .where(
                GraphJob.status == JobStatus.RUNNING.value,
                GraphJob.lease_expires_at.is_not(None),
                GraphJob.lease_expires_at < utcnow(),
            )
            .values(
                status=JobStatus.PENDING.value,
                lease_owner=None,
                lease_expires_at=None,
                last_error_code="lease_expired",
                last_error_message="Worker lease expired; job returned to the queue.",
            )
        )
        await self.session.commit()
        recovered = int(getattr(result, "rowcount", 0) or 0)
        if recovered:
            logger.warning(
                "Recovered expired job leases",
                extra={"extra_fields": {"recovered_jobs": recovered}},
            )
        return recovered

"""Leased PostgreSQL queue for licensing background work."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.licensing.jobs import LicensingJobStatus, LicensingJobType
from app.models import LicensingJob
from app.models.mixins import utcnow


class LicensingJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        *,
        job_type: LicensingJobType,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
        legal_entity_id: uuid.UUID | None = None,
        compliance_case_id: uuid.UUID | None = None,
        max_attempts: int = 6,
        priority: int = 100,
        correlation_id: uuid.UUID | None = None,
    ) -> tuple[LicensingJob, bool]:
        """Enqueue unless an identical key exists. Returns ``(job, created)``."""
        existing = await self.session.scalar(
            select(LicensingJob).where(LicensingJob.idempotency_key == idempotency_key)
        )
        if existing:
            return existing, False
        job = LicensingJob(
            id=uuid.uuid4(),
            job_type=job_type.value,
            status=LicensingJobStatus.PENDING.value,
            priority=priority,
            idempotency_key=idempotency_key,
            payload=payload or {},
            legal_entity_id=legal_entity_id,
            compliance_case_id=compliance_case_id,
            max_attempts=max_attempts,
            available_at=utcnow(),
            correlation_id=correlation_id,
        )
        self.session.add(job)
        await self.session.flush()
        return job, True

    async def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        job_types: list[LicensingJobType] | None = None,
    ) -> LicensingJob | None:
        stmt = (
            select(LicensingJob)
            .where(
                or_(
                    LicensingJob.status == LicensingJobStatus.PENDING.value,
                    LicensingJob.status == LicensingJobStatus.FAILED_RETRYABLE.value,
                ),
                LicensingJob.available_at <= utcnow(),
            )
            .order_by(LicensingJob.priority, LicensingJob.available_at, LicensingJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job_types:
            stmt = stmt.where(LicensingJob.job_type.in_([t.value for t in job_types]))
        job = await self.session.scalar(stmt)
        if not job:
            await self.session.rollback()
            return None
        job.status = LicensingJobStatus.RUNNING.value
        job.lease_owner = worker_id
        job.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
        job.started_at = job.started_at or utcnow()
        job.attempts += 1
        await self.session.commit()
        return job

    async def extend_lease(self, job_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool:
        result = await self.session.execute(
            update(LicensingJob)
            .where(
                LicensingJob.id == job_id,
                LicensingJob.lease_owner == worker_id,
                LicensingJob.status == LicensingJobStatus.RUNNING.value,
            )
            .values(lease_expires_at=utcnow() + timedelta(seconds=lease_seconds))
        )
        await self.session.commit()
        return bool(getattr(result, "rowcount", 0))

    async def mark_completed(self, job: LicensingJob) -> None:
        job.status = LicensingJobStatus.COMPLETED.value
        job.completed_at = utcnow()
        job.lease_owner = None
        job.lease_expires_at = None
        await self.session.commit()

    async def record_failure(
        self, job: LicensingJob, *, error_code: str, error_message: str, retryable: bool
    ) -> None:
        """Retry with exponential backoff until attempts run out, then park."""
        job.last_error_code = error_code[:120]
        job.last_error_message = error_message[:500]
        job.lease_owner = None
        job.lease_expires_at = None
        if retryable and job.attempts < job.max_attempts:
            job.status = LicensingJobStatus.FAILED_RETRYABLE.value
            backoff = min(3600, 2 ** min(job.attempts, 10) * 5)
            job.available_at = utcnow() + timedelta(seconds=backoff)
        else:
            job.status = LicensingJobStatus.FAILED_REVIEW.value
        await self.session.commit()

    async def recover_expired_leases(self) -> int:
        """Return jobs whose worker died back to the queue."""
        result = await self.session.execute(
            update(LicensingJob)
            .where(
                LicensingJob.status == LicensingJobStatus.RUNNING.value,
                LicensingJob.lease_expires_at.is_not(None),
                LicensingJob.lease_expires_at < utcnow(),
            )
            .values(
                status=LicensingJobStatus.FAILED_RETRYABLE.value,
                lease_owner=None,
                lease_expires_at=None,
                available_at=utcnow(),
            )
        )
        await self.session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

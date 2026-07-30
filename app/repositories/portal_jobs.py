"""Leased PostgreSQL queue for isolated browser work."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PortalJob
from app.models.mixins import utcnow
from app.portals.enums import PortalJobStatus, PortalJobType


class PortalJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        *,
        job_type: PortalJobType,
        idempotency_key: str,
        portal_run_id: uuid.UUID | None = None,
        browser_session_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
        priority: int = 100,
        correlation_id: uuid.UUID | None = None,
    ) -> tuple[PortalJob, bool]:
        existing = await self.session.scalar(
            select(PortalJob).where(PortalJob.idempotency_key == idempotency_key)
        )
        if existing:
            return existing, False
        job = PortalJob(
            job_type=job_type.value,
            portal_run_id=portal_run_id,
            browser_session_id=browser_session_id,
            status=PortalJobStatus.PENDING.value,
            priority=priority,
            idempotency_key=idempotency_key,
            payload=payload or {},
            max_attempts=max_attempts,
            available_at=utcnow(),
            correlation_id=correlation_id,
        )
        self.session.add(job)
        await self.session.flush()
        return job, True

    async def claim_next(self, *, worker_id: str, lease_seconds: int) -> PortalJob | None:
        job = await self.session.scalar(
            select(PortalJob)
            .where(
                PortalJob.status.in_(
                    (
                        PortalJobStatus.PENDING.value,
                        PortalJobStatus.FAILED_RETRYABLE.value,
                    )
                ),
                PortalJob.available_at <= utcnow(),
            )
            .order_by(PortalJob.priority, PortalJob.available_at, PortalJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            await self.session.rollback()
            return None
        job.status = PortalJobStatus.RUNNING.value
        job.lease_owner = worker_id
        job.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
        job.started_at = job.started_at or utcnow()
        job.attempts += 1
        await self.session.commit()
        return job

    async def mark_completed(self, job: PortalJob) -> None:
        job.status = PortalJobStatus.COMPLETED.value
        job.completed_at = utcnow()
        job.lease_owner = None
        job.lease_expires_at = None
        await self.session.commit()

    async def mark_waiting_human(self, job: PortalJob) -> None:
        job.status = PortalJobStatus.WAITING_HUMAN.value
        job.lease_owner = None
        job.lease_expires_at = None
        await self.session.commit()

    async def record_failure(
        self,
        job: PortalJob,
        *,
        error_code: str,
        error_message: str,
        retryable: bool,
    ) -> None:
        job.last_error_code = error_code[:120]
        job.last_error_message = error_message[:500]
        job.lease_owner = None
        job.lease_expires_at = None
        if retryable and job.attempts < job.max_attempts:
            job.status = PortalJobStatus.FAILED_RETRYABLE.value
            job.available_at = utcnow() + timedelta(
                seconds=min(300, 5 * (2 ** min(job.attempts, 6)))
            )
        else:
            job.status = PortalJobStatus.FAILED_REVIEW.value
        await self.session.commit()

    async def recover_expired_leases(self) -> int:
        result = await self.session.execute(
            update(PortalJob)
            .where(
                PortalJob.status == PortalJobStatus.RUNNING.value,
                PortalJob.lease_expires_at.is_not(None),
                PortalJob.lease_expires_at < utcnow(),
            )
            .values(
                status=PortalJobStatus.FAILED_RETRYABLE.value,
                lease_owner=None,
                lease_expires_at=None,
                available_at=utcnow(),
            )
        )
        await self.session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    async def cancel_pending_for_run(self, run_id: uuid.UUID) -> int:
        result = await self.session.execute(
            update(PortalJob)
            .where(
                PortalJob.portal_run_id == run_id,
                PortalJob.status.in_(
                    (
                        PortalJobStatus.PENDING.value,
                        PortalJobStatus.FAILED_RETRYABLE.value,
                        PortalJobStatus.WAITING_HUMAN.value,
                    )
                ),
            )
            .values(status=PortalJobStatus.CANCELLED.value)
        )
        return int(getattr(result, "rowcount", 0) or 0)

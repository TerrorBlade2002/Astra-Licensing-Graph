"""PostgreSQL leased communication jobs with exact idempotency keys."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.communications.enums import CommunicationJobStatus
from app.models import CommunicationJob
from app.models.mixins import utcnow


class CommunicationJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        *,
        job_type: str,
        idempotency_key: str,
        draft_id: uuid.UUID | None = None,
        email_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        payload: dict[str, object] | None = None,
        priority: int = 100,
        max_attempts: int = 4,
        delay_seconds: int = 0,
    ) -> tuple[CommunicationJob, bool]:
        existing = await self.session.scalar(
            select(CommunicationJob).where(CommunicationJob.idempotency_key == idempotency_key)
        )
        if existing:
            return existing, False
        job = CommunicationJob(
            job_type=job_type,
            outbound_draft_id=draft_id,
            email_id=email_id,
            task_id=task_id,
            status=CommunicationJobStatus.PENDING,
            priority=priority,
            idempotency_key=idempotency_key,
            payload=payload or {},
            attempts=0,
            max_attempts=max_attempts,
            available_at=utcnow() + timedelta(seconds=max(0, delay_seconds)),
        )
        self.session.add(job)
        await self.session.flush()
        return job, True

    async def claim(self, worker_id: str, lease_seconds: int = 60) -> CommunicationJob | None:
        now = utcnow()
        job = await self.session.scalar(
            select(CommunicationJob)
            .where(
                or_(
                    and_(
                        CommunicationJob.status.in_(
                            [
                                CommunicationJobStatus.PENDING,
                                CommunicationJobStatus.FAILED_RETRYABLE,
                            ]
                        ),
                        CommunicationJob.available_at <= now,
                    ),
                    and_(
                        CommunicationJob.status == CommunicationJobStatus.RUNNING,
                        CommunicationJob.lease_expires_at.is_not(None),
                        CommunicationJob.lease_expires_at <= now,
                    ),
                ),
                CommunicationJob.attempts < CommunicationJob.max_attempts,
            )
            .order_by(CommunicationJob.priority, CommunicationJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.status = CommunicationJobStatus.RUNNING
        job.lease_owner = worker_id
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.started_at = now
        job.attempts += 1
        await self.session.commit()
        return job

    async def extend_lease(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> bool:
        now = utcnow()
        result = await self.session.execute(
            update(CommunicationJob)
            .where(
                CommunicationJob.id == job_id,
                CommunicationJob.status == CommunicationJobStatus.RUNNING,
                CommunicationJob.lease_owner == worker_id,
            )
            .values(lease_expires_at=now + timedelta(seconds=lease_seconds))
        )
        await self.session.commit()
        return bool(getattr(result, "rowcount", 0))

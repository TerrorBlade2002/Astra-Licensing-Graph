"""Leased PostgreSQL queue for document and SharePoint work."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.enums import DocumentJobStatus, DocumentJobType
from app.models import DocumentJob
from app.models.mixins import utcnow


class DocumentJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        *,
        job_type: DocumentJobType,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
        document_id: uuid.UUID | None = None,
        document_version_id: uuid.UUID | None = None,
        drive_id: uuid.UUID | None = None,
        source_email_attachment_id: uuid.UUID | None = None,
        max_attempts: int = 6,
        priority: int = 100,
        correlation_id: uuid.UUID | None = None,
    ) -> tuple[DocumentJob, bool]:
        existing = await self.session.scalar(
            select(DocumentJob).where(DocumentJob.idempotency_key == idempotency_key)
        )
        if existing:
            return existing, False
        job = DocumentJob(
            id=uuid.uuid4(),
            job_type=job_type.value,
            document_id=document_id,
            document_version_id=document_version_id,
            drive_id=drive_id,
            source_email_attachment_id=source_email_attachment_id,
            status=DocumentJobStatus.PENDING.value,
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

    async def claim_next(
        self, *, worker_id: str, lease_seconds: int, job_types: list[DocumentJobType] | None = None
    ) -> DocumentJob | None:
        stmt = (
            select(DocumentJob)
            .where(
                or_(
                    DocumentJob.status == DocumentJobStatus.PENDING.value,
                    DocumentJob.status == DocumentJobStatus.FAILED_RETRYABLE.value,
                ),
                DocumentJob.available_at <= utcnow(),
            )
            .order_by(DocumentJob.priority, DocumentJob.available_at, DocumentJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job_types:
            stmt = stmt.where(DocumentJob.job_type.in_([value.value for value in job_types]))
        job = await self.session.scalar(stmt)
        if not job:
            await self.session.rollback()
            return None
        job.status = DocumentJobStatus.RUNNING.value
        job.lease_owner = worker_id
        job.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
        job.started_at = job.started_at or utcnow()
        job.attempts += 1
        await self.session.commit()
        return job

    async def extend_lease(self, job_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool:
        result = await self.session.execute(
            update(DocumentJob)
            .where(
                DocumentJob.id == job_id,
                DocumentJob.lease_owner == worker_id,
                DocumentJob.status == DocumentJobStatus.RUNNING.value,
            )
            .values(lease_expires_at=utcnow() + timedelta(seconds=lease_seconds))
        )
        await self.session.commit()
        return bool(getattr(result, "rowcount", 0))

"""Job-queue service: enqueue helpers and failure escalation policy."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.correlation import get_correlation_id
from app.jobs.enums import JobType
from app.jobs.repository import EnqueueResult, GraphJobRepository
from app.models import AuditEvent, GraphJob, OutboxEvent
from app.models.mixins import utcnow

logger = logging.getLogger(__name__)


def _correlation_uuid() -> uuid.UUID | None:
    raw = get_correlation_id()
    try:
        return uuid.UUID(raw) if raw else None
    except ValueError:
        return None


class GraphJobService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = GraphJobRepository(session)

    async def enqueue_sync_folder(
        self,
        *,
        mailbox_id: uuid.UUID,
        folder_id: uuid.UUID,
        reason: str,
        idempotency_key: str | None = None,
        priority: int = 100,
        delay_seconds: float = 0,
    ) -> EnqueueResult:
        return await self.repo.enqueue(
            job_type=JobType.SYNC_FOLDER,
            idempotency_key=idempotency_key or f"sync:{folder_id}:{uuid.uuid4()}",
            max_attempts=self.settings.graph_job_max_attempts,
            mailbox_id=mailbox_id,
            folder_id=folder_id,
            reason=reason,
            priority=priority,
            delay_seconds=delay_seconds,
            correlation_id=_correlation_uuid(),
        )

    async def enqueue_ingest_email(
        self,
        *,
        mailbox_id: uuid.UUID,
        email_id: uuid.UUID,
        reason: str,
        idempotency_key: str | None = None,
        priority: int = 100,
    ) -> EnqueueResult:
        return await self.repo.enqueue(
            job_type=JobType.INGEST_EMAIL,
            idempotency_key=idempotency_key or f"ingest:{email_id}:{uuid.uuid4()}",
            max_attempts=self.settings.graph_job_max_attempts,
            mailbox_id=mailbox_id,
            email_id=email_id,
            reason=reason,
            priority=priority,
            correlation_id=_correlation_uuid(),
        )

    async def enqueue_classify_email(
        self,
        *,
        mailbox_id: uuid.UUID,
        email_id: uuid.UUID,
        reason: str,
        reclassification: bool = False,
    ) -> EnqueueResult:
        return await self.repo.enqueue(
            job_type=JobType.CLASSIFY_EMAIL,
            idempotency_key=(
                f"classify:{email_id}:{'reclass' if reclassification else 'initial'}:{uuid.uuid4()}"
            ),
            max_attempts=self.settings.classification_job_max_attempts,
            mailbox_id=mailbox_id,
            email_id=email_id,
            reason=reason,
            payload={"reclassification": reclassification},
            priority=80,
            correlation_id=_correlation_uuid(),
        )

    async def enqueue_subscription_maintenance(
        self,
        *,
        job_type: JobType,
        mailbox_id: uuid.UUID,
        folder_id: uuid.UUID,
        reason: str,
        idempotency_key: str | None = None,
        priority: int = 50,
    ) -> EnqueueResult:
        if job_type not in (
            JobType.ENSURE_SUBSCRIPTION,
            JobType.RENEW_SUBSCRIPTION,
            JobType.RECREATE_SUBSCRIPTION,
        ):
            raise ValueError(f"Not a subscription-maintenance job type: {job_type}")
        return await self.repo.enqueue(
            job_type=job_type,
            idempotency_key=idempotency_key
            or f"{job_type.value.lower()}:{folder_id}:{uuid.uuid4()}",
            max_attempts=self.settings.graph_job_max_attempts,
            mailbox_id=mailbox_id,
            folder_id=folder_id,
            reason=reason,
            priority=priority,
            correlation_id=_correlation_uuid(),
        )

    # ---------------------------------------------------------------- failure

    async def record_failure(
        self, job: GraphJob, *, error_code: str, error_message: str, retryable: bool
    ) -> None:
        """Apply the retry/escalation policy for a failed job attempt."""
        if retryable and job.attempts < job.max_attempts:
            await self.repo.mark_retryable_failure(
                job,
                error_code=error_code,
                error_message=error_message,
                retry_base_seconds=self.settings.graph_job_retry_base_seconds,
                retry_max_seconds=self.settings.graph_job_retry_max_seconds,
            )
            return

        final_code = error_code if retryable is False else "max_attempts_exhausted"
        now = utcnow()
        self.session.add(
            AuditEvent(
                actor_type="SYSTEM",
                actor_id=job.lease_owner or "graph-worker",
                entity_type="graph_job",
                entity_id=str(job.id),
                action="job_failed_review",
                after_data={
                    "job_type": job.job_type,
                    "attempts": job.attempts,
                    "error_code": final_code,
                },
                event_metadata={"reason": job.reason},
                correlation_id=job.correlation_id,
                occurred_at=now,
            )
        )
        self.session.add(
            OutboxEvent(
                aggregate_type="graph_job",
                aggregate_id=str(job.id),
                event_type="graph_job.failed_review",
                payload={
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "error_code": final_code,
                    "attempts": job.attempts,
                },
                idempotency_key=f"graph-job-review:{job.id}:{job.attempts}",
                status="PENDING",
                available_at=now,
            )
        )
        await self.repo.mark_review_failure(job, error_code=final_code, error_message=error_message)
        logger.error(
            "Graph job moved to FAILED_REVIEW",
            extra={
                "extra_fields": {
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "attempts": job.attempts,
                    "error_code": final_code,
                }
            },
        )

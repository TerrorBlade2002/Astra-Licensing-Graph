"""INGEST_EMAIL job handler."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError
from app.graph.attachments import GraphAttachmentApi
from app.graph.messages import GraphMessageApi
from app.models import GraphJob
from app.services.email_ingestion import EmailIngestionService
from app.workers.context import WorkerContext


async def handle_ingest_email(ctx: WorkerContext, session: AsyncSession, job: GraphJob) -> None:
    if job.email_id is None:
        raise DomainError("INGEST_EMAIL job is missing the email id.")
    service = EmailIngestionService(
        session,
        ctx.settings,
        GraphMessageApi(ctx.graph_client),
        GraphAttachmentApi(ctx.graph_client),
        ctx.evidence_store,
        worker_id=ctx.worker_id,
    )
    await service.ingest(job.email_id, job_id=job.id)

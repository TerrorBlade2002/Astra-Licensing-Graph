"""Leased worker for document lifecycle and SharePoint reconciliation jobs."""

from __future__ import annotations

import asyncio

from app.documents.enums import DocumentJobStatus, DocumentJobType
from app.models.mixins import utcnow
from app.repositories.document_jobs import DocumentJobRepository
from app.services.document_catalog import DocumentCatalogService
from app.services.document_reconciliation import DocumentReconciliationService
from app.services.sharepoint_bootstrap import SharePointBootstrapService
from app.sharepoint.client import SharePointClient
from app.workers.context import WorkerContext

DOCUMENT_QUEUE_TYPES = {
    "documents": [
        DocumentJobType.UPLOAD_DOCUMENT,
        DocumentJobType.PROMOTE_ATTACHMENT,
        DocumentJobType.SYNC_DOCUMENT_METADATA,
        DocumentJobType.VERIFY_DOCUMENT_HASH,
        DocumentJobType.MIGRATE_EVIDENCE,
        DocumentJobType.MARK_EXPIRED_DOCUMENTS,
    ],
    "sharepoint": [
        DocumentJobType.VERIFY_SITE_ACCESS,
        DocumentJobType.BOOTSTRAP_REPOSITORY,
        DocumentJobType.RECONCILE_DRIVE,
    ],
}


class DocumentWorkerRunner:
    def __init__(
        self,
        ctx: WorkerContext,
        *,
        job_types: list[DocumentJobType],
        once: bool,
        max_jobs: int | None,
    ) -> None:
        self.ctx = ctx
        self.job_types = job_types
        self.once = once
        self.max_jobs = max_jobs
        self.processed = 0

    async def run(self) -> int:
        sharepoint = SharePointClient(self.ctx.graph_client, self.ctx.settings)
        try:
            while True:
                worked = await self._cycle(sharepoint)
                if (self.once and not worked) or (
                    self.max_jobs is not None and self.processed >= self.max_jobs
                ):
                    return self.processed
                if not worked:
                    await asyncio.sleep(self.ctx.settings.graph_worker_poll_interval_seconds)
        finally:
            await sharepoint.aclose()

    async def _cycle(self, client: SharePointClient) -> bool:
        async with self.ctx.session_factory() as session:
            repo = DocumentJobRepository(session)
            job = await repo.claim_next(
                worker_id=self.ctx.worker_id,
                lease_seconds=self.ctx.settings.graph_job_lease_seconds,
                job_types=self.job_types,
            )
            if not job:
                return False
            try:
                if job.job_type == DocumentJobType.BOOTSTRAP_REPOSITORY.value:
                    await SharePointBootstrapService(session, client, self.ctx.settings).apply()
                elif job.job_type == DocumentJobType.RECONCILE_DRIVE.value and job.drive_id:
                    await DocumentReconciliationService(session, client).reconcile(job.drive_id)
                elif job.job_type == DocumentJobType.MARK_EXPIRED_DOCUMENTS.value:
                    await DocumentCatalogService(session).mark_expired()
                else:
                    raise ValueError(
                        "Document job requires operator review or a source-specific handler."
                    )
                job.status = DocumentJobStatus.COMPLETED.value
                job.completed_at = utcnow()
                job.lease_owner = None
                job.lease_expires_at = None
                await session.commit()
            except Exception as exc:
                await session.rollback()
                job = await session.get(type(job), job.id)
                assert job is not None
                job.status = DocumentJobStatus.FAILED_REVIEW.value
                job.last_error_code = type(exc).__name__[:100]
                job.last_error_message = str(exc)[:500]
                job.lease_owner = None
                job.lease_expires_at = None
                await session.commit()
            self.processed += 1
            return True


def resolve_document_job_types(queues: str) -> list[DocumentJobType]:
    result: list[DocumentJobType] = []
    for name in (value.strip().lower() for value in queues.split(",")):
        if name:
            result.extend(DOCUMENT_QUEUE_TYPES[name])
    return result

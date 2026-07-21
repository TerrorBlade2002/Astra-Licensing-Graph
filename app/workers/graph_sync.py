"""SYNC_FOLDER job handler."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError
from app.graph.delta import GraphDeltaApi
from app.models import GraphJob
from app.services.graph_sync import FolderDeltaSyncService
from app.workers.context import WorkerContext


async def handle_sync_folder(ctx: WorkerContext, session: AsyncSession, job: GraphJob) -> None:
    if job.mailbox_id is None or job.folder_id is None:
        raise DomainError("SYNC_FOLDER job is missing mailbox or folder.")
    delta_api = GraphDeltaApi(
        ctx.graph_client,
        page_size=ctx.settings.graph_delta_page_size,
        select_fields=ctx.settings.graph_delta_select,
    )
    service = FolderDeltaSyncService(session, ctx.settings, delta_api, worker_id=ctx.worker_id)
    await service.sync_folder(job.mailbox_id, job.folder_id, job_id=job.id)

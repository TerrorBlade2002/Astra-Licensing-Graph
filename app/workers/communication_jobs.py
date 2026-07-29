"""Durable communication worker using the PostgreSQL lease queue."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.auth.actors import CurrentActor
from app.communications.enums import (
    CommunicationDraftStatus,
    CommunicationJobStatus,
    CommunicationJobType,
    MoveAttemptStatus,
)
from app.domain.enums import ActorType
from app.models import MessageMoveAttempt, OutboundDraft
from app.models.mixins import utcnow
from app.repositories.communication_jobs import CommunicationJobRepository
from app.services.graph_draft_attachment_service import GraphDraftAttachmentService
from app.services.graph_draft_service import GraphDraftService
from app.services.outbound_send_service import OutboundSendService
from app.services.sent_reconciliation_service import SentReconciliationService
from app.services.source_move_service import SourceMoveService
from app.services.workflow_completion_service import WorkflowCompletionService
from app.workers.context import WorkerContext


class CommunicationWorkerRunner:
    def __init__(self, context: WorkerContext, *, once: bool = False, max_jobs: int | None = None):
        self.context, self.once, self.max_jobs = context, once, max_jobs

    async def run(self) -> int:
        processed = 0
        actor = CurrentActor(
            actor_type=ActorType.SYSTEM,
            actor_id=self.context.worker_id,
            tenant_id="system",
            object_id=self.context.worker_id,
            roles=(),
        )
        while self.max_jobs is None or processed < self.max_jobs:
            async with self.context.session_factory() as session:
                job = await CommunicationJobRepository(session).claim(self.context.worker_id)
                if job is None:
                    if self.once:
                        return processed
                    await asyncio.sleep(self.context.settings.graph_worker_poll_interval_seconds)
                    continue
                lease_task = asyncio.create_task(self._extend_lease_loop(job.id))
                try:
                    if (
                        job.job_type == CommunicationJobType.CREATE_GRAPH_DRAFT
                        and job.outbound_draft_id
                    ):
                        await GraphDraftService(
                            session, self.context.settings, self.context.graph_client
                        ).create(job.outbound_draft_id, actor)
                    elif (
                        job.job_type == CommunicationJobType.SYNC_GRAPH_DRAFT
                        and job.outbound_draft_id
                    ):
                        await GraphDraftService(
                            session, self.context.settings, self.context.graph_client
                        ).sync(job.outbound_draft_id, actor)
                    elif (
                        job.job_type == CommunicationJobType.RECONCILE_GRAPH_DRAFT
                        and job.outbound_draft_id
                    ):
                        await GraphDraftService(
                            session, self.context.settings, self.context.graph_client
                        ).reconcile(job.outbound_draft_id, actor)
                    elif (
                        job.job_type == CommunicationJobType.UPLOAD_DRAFT_ATTACHMENTS
                        and job.outbound_draft_id
                    ):
                        uploaded = await GraphDraftAttachmentService(
                            session, self.context.settings, self.context.graph_client
                        ).upload_pending(job.outbound_draft_id, actor)
                        if uploaded:
                            await GraphDraftService(
                                session,
                                self.context.settings,
                                self.context.graph_client,
                            ).sync(
                                job.outbound_draft_id,
                                actor,
                                allow_expected_transport_metadata_change=True,
                            )
                    elif job.job_type == CommunicationJobType.SEND_DRAFT and job.outbound_draft_id:
                        await OutboundSendService(
                            session, self.context.settings, self.context.graph_client
                        ).execute(job.outbound_draft_id, job_id=job.id)
                    elif (
                        job.job_type == CommunicationJobType.RECONCILE_SEND
                        and job.outbound_draft_id
                    ):
                        await SentReconciliationService(
                            session, self.context.settings, self.context.graph_client
                        ).reconcile(job.outbound_draft_id)
                    elif job.job_type == CommunicationJobType.MOVE_SOURCE_MESSAGE and job.email_id:
                        await SourceMoveService(
                            session, self.context.settings, self.context.graph_client
                        ).execute(job.email_id)
                    elif job.job_type == CommunicationJobType.VERIFY_SOURCE_MOVE and job.email_id:
                        await SourceMoveService(
                            session, self.context.settings, self.context.graph_client
                        ).reconcile(job.email_id)
                    elif (
                        job.job_type == CommunicationJobType.COMPLETE_EMAIL_WORKFLOW
                        and job.email_id
                    ):
                        await WorkflowCompletionService(session).complete(job.email_id, actor)
                    else:
                        raise ValueError("Communication job has invalid type or target.")
                    lease_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await lease_task
                    job.status = CommunicationJobStatus.COMPLETED
                    job.completed_at = utcnow()
                    job.lease_owner = None
                    job.lease_expires_at = None
                    await session.commit()
                except Exception as exc:
                    lease_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await lease_task
                    await session.rollback()
                    job = await session.get(type(job), job.id)
                    if job:
                        job.status = (
                            CommunicationJobStatus.FAILED_RETRYABLE
                            if job.attempts < job.max_attempts
                            else CommunicationJobStatus.FAILED_REVIEW
                        )
                        job.last_error_code = type(exc).__name__
                        job.last_error_message = (
                            "Communication operation failed; see the safe error code."
                        )
                        job.lease_owner = None
                        job.lease_expires_at = None
                        if job.status == CommunicationJobStatus.FAILED_RETRYABLE:
                            delay = min(300, 2 ** min(job.attempts, 8))
                            job.available_at = utcnow() + timedelta(seconds=delay)
                        elif job.job_type == CommunicationJobType.RECONCILE_SEND:
                            draft = (
                                await session.get(OutboundDraft, job.outbound_draft_id)
                                if job.outbound_draft_id
                                else None
                            )
                            if draft and draft.draft_status in {
                                CommunicationDraftStatus.SEND_ACCEPTED,
                                CommunicationDraftStatus.SEND_AMBIGUOUS,
                            }:
                                draft.draft_status = CommunicationDraftStatus.SEND_FAILED_REVIEW
                        elif job.job_type == CommunicationJobType.VERIFY_SOURCE_MOVE:
                            attempt = (
                                await session.scalar(
                                    select(MessageMoveAttempt)
                                    .where(MessageMoveAttempt.email_id == job.email_id)
                                    .order_by(MessageMoveAttempt.attempt_number.desc())
                                )
                                if job.email_id
                                else None
                            )
                            if attempt and attempt.status == MoveAttemptStatus.AMBIGUOUS:
                                attempt.status = MoveAttemptStatus.FAILED_REVIEW
                                attempt.error_code = "MOVE_RECONCILIATION_EXHAUSTED"
                                attempt.error_message = (
                                    "Move ambiguity requires explicit operator review."
                                )
                        elif job.job_type == CommunicationJobType.RECONCILE_GRAPH_DRAFT:
                            draft = (
                                await session.get(OutboundDraft, job.outbound_draft_id)
                                if job.outbound_draft_id
                                else None
                            )
                            if (
                                draft
                                and draft.draft_status
                                == CommunicationDraftStatus.GRAPH_DRAFT_PENDING
                            ):
                                draft.draft_status = CommunicationDraftStatus.SEND_FAILED_REVIEW
                        await session.commit()
                processed += 1
        return processed

    async def _extend_lease_loop(self, job_id: uuid.UUID) -> None:
        lease_seconds = max(60, self.context.settings.graph_job_lease_seconds)
        interval = max(10, min(lease_seconds // 3, 30))
        while True:
            await asyncio.sleep(interval)
            async with self.context.session_factory() as session:
                extended = await CommunicationJobRepository(session).extend_lease(
                    job_id,
                    worker_id=self.context.worker_id,
                    lease_seconds=lease_seconds,
                )
                if not extended:
                    return

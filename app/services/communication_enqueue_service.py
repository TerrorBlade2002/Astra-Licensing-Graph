"""Queue-only user mutations for non-transactional Graph work."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.auth.roles import Role, has_role
from app.communications.audit import add_communication_audit
from app.communications.enums import (
    ApprovalDecision,
    CommunicationDraftStatus,
    CommunicationJobType,
)
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import COMMUNICATION_SEND_JOBS_TOTAL
from app.models import OutboundDraft, SendApproval
from app.models.mixins import utcnow
from app.repositories.communication_jobs import CommunicationJobRepository


class CommunicationEnqueueService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings

    async def send(
        self,
        draft_id: uuid.UUID,
        *,
        idempotency_key: str,
        explicit_confirmation: bool,
        actor: CurrentActor,
    ) -> tuple[uuid.UUID, bool]:
        if not explicit_confirmation:
            raise ValueError("Explicit send confirmation is required.")
        if not idempotency_key.strip():
            raise ValueError("A client idempotency key is required.")
        if not has_role(actor.roles, Role.SENDER):
            raise StateConflictError("Licensing.Sender role is required to queue a send.")
        if not self.settings.communications_enabled or not self.settings.graph_send_enabled:
            raise StateConflictError("Graph send is disabled.")
        draft = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.id == draft_id).with_for_update()
        )
        if draft is None or draft.draft_status not in {
            CommunicationDraftStatus.APPROVED_TO_SEND,
            CommunicationDraftStatus.SEND_QUEUED,
        }:
            raise StateConflictError("Draft is not approved to send.")
        approval = await self.session.scalar(
            select(SendApproval).where(
                SendApproval.outbound_draft_id == draft.id,
                SendApproval.decision == ApprovalDecision.APPROVED,
                SendApproval.invalidated_at.is_(None),
            )
        )
        if approval is None or approval.approval_snapshot_sha256 != draft.approval_snapshot_sha256:
            raise StateConflictError("Current exact-snapshot send approval is missing.")
        job, created = await CommunicationJobRepository(self.session).enqueue(
            job_type=CommunicationJobType.SEND_DRAFT,
            # The client key is required and audited in the payload, while the
            # durable job key coalesces every request for the same approved
            # snapshot. A second browser request can never create a second
            # executable send job.
            idempotency_key=f"send:{draft.id}:{approval.approval_snapshot_sha256}",
            draft_id=draft.id,
            email_id=draft.email_id,
            task_id=draft.task_id,
            payload={
                "approval_id": str(approval.id),
                "queued_by": actor.actor_id,
                "client_idempotency_key": idempotency_key,
            },
            priority=10,
            max_attempts=self.settings.communication_send_job_max_attempts,
        )
        if created:
            draft.draft_status = CommunicationDraftStatus.SEND_QUEUED
            draft.send_queued_at = utcnow()
            COMMUNICATION_SEND_JOBS_TOTAL.inc()
            add_communication_audit(
                self.session,
                actor=actor,
                entity_type="outbound_draft",
                entity_id=draft.id,
                action="approved_send_queued",
                before={"status": CommunicationDraftStatus.APPROVED_TO_SEND},
                after={"status": CommunicationDraftStatus.SEND_QUEUED},
                metadata={"communication_job_id": str(job.id)},
            )
        await self.session.commit()
        return job.id, created

    async def reconcile_send(self, draft_id: uuid.UUID) -> tuple[uuid.UUID, bool]:
        draft = await self.session.get(OutboundDraft, draft_id)
        if draft is None:
            raise NotFoundError("Draft does not exist.")
        job, created = await CommunicationJobRepository(self.session).enqueue(
            job_type=CommunicationJobType.RECONCILE_SEND,
            idempotency_key=f"reconcile-send:{draft.id}:{draft.local_revision}",
            draft_id=draft.id,
            email_id=draft.email_id,
            task_id=draft.task_id,
            priority=20,
            max_attempts=self.settings.communication_send_reconciliation_max_attempts,
        )
        await self.session.commit()
        return job.id, created

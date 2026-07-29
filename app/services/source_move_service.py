"""Source-message move saga executed only after communication prerequisites."""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.communications.audit import add_system_communication_audit
from app.communications.enums import (
    CommunicationDraftStatus,
    CommunicationJobType,
    MoveAttemptStatus,
    ResponseType,
)
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import COMMUNICATION_MOVE_FAILURES_TOTAL, COMMUNICATION_MOVE_JOBS_TOTAL
from app.graph.client import GraphHttpClient
from app.graph.drafts import GraphDraftClient
from app.graph.errors import GraphApiError, GraphAuthError
from app.graph.moves import GraphMoveClient
from app.models import (
    Email,
    LicensingTask,
    Mailbox,
    MessageMoveAttempt,
    OutboundDraft,
    ResponsePlan,
)
from app.models.mixins import utcnow
from app.repositories.communication_jobs import CommunicationJobRepository


class SourceMoveService:
    def __init__(self, session: AsyncSession, settings: Settings, graph: GraphHttpClient) -> None:
        self.session, self.settings, self.client = session, settings, GraphMoveClient(graph)

    async def execute(self, email_id: uuid.UUID) -> MessageMoveAttempt:
        if not self.settings.graph_message_move_enabled:
            raise StateConflictError("Graph source-message move is disabled.")
        email = await self.session.get(Email, email_id)
        task = await self.session.scalar(
            select(LicensingTask).where(LicensingTask.email_id == email_id)
        )
        plan = await self.session.scalar(
            select(ResponsePlan).where(ResponsePlan.email_id == email_id)
        )
        if email is None or task is None or plan is None:
            raise NotFoundError("Email communication context is missing.")
        latest = await self.session.scalar(
            select(MessageMoveAttempt)
            .where(MessageMoveAttempt.email_id == email.id)
            .order_by(MessageMoveAttempt.attempt_number.desc())
        )
        if latest and latest.status == MoveAttemptStatus.VERIFIED:
            return latest
        if latest and latest.status == MoveAttemptStatus.STARTED:
            latest.status = MoveAttemptStatus.AMBIGUOUS
            latest.error_code = "STALE_MOVE_LEASE"
            latest.error_message = (
                "The move worker stopped after persisting intent; reconciliation is required."
            )
            await self._enqueue_reconciliation(latest)
            add_system_communication_audit(
                self.session,
                entity_type="message_move_attempt",
                entity_id=latest.id,
                action="stale_source_move_marked_ambiguous",
                after={"status": latest.status},
            )
            await self.session.commit()
            return latest
        if latest and latest.status == MoveAttemptStatus.AMBIGUOUS:
            await self._enqueue_reconciliation(latest)
            await self.session.commit()
            return latest
        if plan.response_type != ResponseType.NO_RESPONSE_REQUIRED:
            draft = await self.session.scalar(
                select(OutboundDraft).where(OutboundDraft.response_plan_id == plan.id)
            )
            if draft is None or draft.draft_status != CommunicationDraftStatus.SENT_COPY_VERIFIED:
                raise StateConflictError("Source move is blocked until the sent copy is verified.")
        destination_id = task.destination_folder_id
        destination_name = task.destination_folder_name
        if self.settings.communication_move_policy == "COMPLETED_FOLDER":
            from app.models import MailboxFolder

            folder = await self.session.scalar(
                select(MailboxFolder).where(
                    MailboxFolder.mailbox_id == email.mailbox_id,
                    MailboxFolder.display_name == self.settings.communication_completed_folder_name,
                )
            )
            if folder:
                destination_id, destination_name = folder.graph_folder_id, folder.display_name
        if not destination_id or not destination_name:
            raise StateConflictError("Destination folder is not verified.")
        count = await self.session.scalar(
            select(func.count(MessageMoveAttempt.id)).where(MessageMoveAttempt.email_id == email.id)
        )
        attempt = MessageMoveAttempt(
            email_id=email.id,
            task_id=task.id,
            source_graph_message_id=email.graph_message_id,
            destination_folder_id=destination_id,
            destination_folder_name=destination_name,
            attempt_number=int(count or 0) + 1,
            status=MoveAttemptStatus.STARTED,
            started_at=utcnow(),
        )
        self.session.add(attempt)
        await self.session.flush()
        add_system_communication_audit(
            self.session,
            entity_type="message_move_attempt",
            entity_id=attempt.id,
            action="source_move_intent_persisted",
            after={"status": attempt.status, "attempt_number": attempt.attempt_number},
            metadata={"email_id": str(email.id), "task_id": str(task.id)},
        )
        await self.session.commit()
        COMMUNICATION_MOVE_JOBS_TOTAL.inc()
        mailbox = await self.session.get(Mailbox, email.mailbox_id)
        if mailbox is None:
            raise NotFoundError("Mailbox does not exist.")
        try:
            moved = await self.client.move(
                mailbox.graph_user_id or mailbox.address,
                email.graph_message_id,
                destination_id,
            )
        except (GraphAuthError, httpx.ConnectError) as exc:
            attempt.error_code = getattr(exc, "error_code", None) or type(exc).__name__
            attempt.error_message = (
                "Move request was not transmitted; a bounded safe retry was queued."
            )
            if attempt.attempt_number >= self.settings.communication_move_job_max_attempts:
                attempt.status = MoveAttemptStatus.FAILED_REVIEW
                attempt.error_message = "The bounded safe move retry budget was exhausted."
                COMMUNICATION_MOVE_FAILURES_TOTAL.inc()
            else:
                attempt.status = MoveAttemptStatus.FAILED_RETRYABLE
                await CommunicationJobRepository(self.session).enqueue(
                    job_type=CommunicationJobType.MOVE_SOURCE_MESSAGE,
                    idempotency_key=f"move-pretransmission-retry:{attempt.id}",
                    email_id=email.id,
                    task_id=task.id,
                    priority=30,
                    max_attempts=1,
                )
            await self.session.commit()
            return attempt
        except (httpx.TimeoutException, httpx.ReadError, httpx.WriteError) as exc:
            attempt.status = MoveAttemptStatus.AMBIGUOUS
            attempt.error_code = type(exc).__name__
            attempt.error_message = "Move outcome is ambiguous; reconciliation is required."
            COMMUNICATION_MOVE_FAILURES_TOTAL.inc()
            await self._enqueue_reconciliation(attempt)
            add_system_communication_audit(
                self.session,
                entity_type="message_move_attempt",
                entity_id=attempt.id,
                action="source_move_outcome_marked_ambiguous",
                after={"status": attempt.status},
            )
            await self.session.commit()
            return attempt
        except GraphApiError as exc:
            attempt.http_status = exc.status_code
            attempt.graph_request_id = exc.request_id
            attempt.graph_client_request_id = exc.client_request_id
            attempt.error_code = exc.graph_error_code or f"HTTP_{exc.status_code}"
            attempt.error_message = exc.safe_message
            if exc.status_code in {408, 500, 502, 503, 504}:
                # A move is non-idempotent. A gateway/server timeout can hide a
                # successful move, so inspect the immutable source ID first.
                attempt.status = MoveAttemptStatus.AMBIGUOUS
                attempt.error_message = (
                    "Move outcome is ambiguous; destination reconciliation is required."
                )
                COMMUNICATION_MOVE_FAILURES_TOTAL.inc()
                await self._enqueue_reconciliation(attempt)
                add_system_communication_audit(
                    self.session,
                    entity_type="message_move_attempt",
                    entity_id=attempt.id,
                    action="source_move_http_outcome_marked_ambiguous",
                    after={"status": attempt.status, "http_status": attempt.http_status},
                )
            elif exc.status_code == 429:
                if attempt.attempt_number >= self.settings.communication_move_job_max_attempts:
                    attempt.status = MoveAttemptStatus.FAILED_REVIEW
                    attempt.error_message = "The bounded safe move retry budget was exhausted."
                    COMMUNICATION_MOVE_FAILURES_TOTAL.inc()
                else:
                    attempt.status = MoveAttemptStatus.FAILED_RETRYABLE
                    await CommunicationJobRepository(self.session).enqueue(
                        job_type=CommunicationJobType.MOVE_SOURCE_MESSAGE,
                        idempotency_key=f"move-safe-retry:{attempt.id}",
                        email_id=email.id,
                        task_id=task.id,
                        priority=30,
                        max_attempts=1,
                    )
            else:
                attempt.status = MoveAttemptStatus.FAILED_REVIEW
                COMMUNICATION_MOVE_FAILURES_TOTAL.inc()
            await self.session.commit()
            return attempt
        except ValueError as exc:
            attempt.status = MoveAttemptStatus.FAILED_REVIEW
            attempt.error_code = type(exc).__name__
            attempt.error_message = "Graph move response did not verify the destination."
            COMMUNICATION_MOVE_FAILURES_TOTAL.inc()
            await self.session.commit()
            return attempt
        attempt.status = MoveAttemptStatus.VERIFIED
        attempt.http_status = 201
        attempt.returned_graph_message_id = moved.message_id
        attempt.returned_parent_folder_id = moved.parent_folder_id
        attempt.graph_request_id = moved.request_id
        attempt.graph_client_request_id = moved.client_request_id
        attempt.moved_at = attempt.verified_at = utcnow()
        await CommunicationJobRepository(self.session).enqueue(
            job_type=CommunicationJobType.COMPLETE_EMAIL_WORKFLOW,
            idempotency_key=f"complete-after-move:{attempt.id}",
            email_id=email.id,
            task_id=task.id,
            priority=40,
            max_attempts=1,
        )
        add_system_communication_audit(
            self.session,
            entity_type="message_move_attempt",
            entity_id=attempt.id,
            action="source_move_verified",
            after={"status": attempt.status},
            metadata={"destination_folder_id": attempt.destination_folder_id},
        )
        await self.session.commit()
        return attempt

    async def _enqueue_reconciliation(self, attempt: MessageMoveAttempt) -> None:
        await CommunicationJobRepository(self.session).enqueue(
            job_type=CommunicationJobType.VERIFY_SOURCE_MOVE,
            idempotency_key=f"verify-ambiguous-move:{attempt.id}",
            email_id=attempt.email_id,
            task_id=attempt.task_id,
            priority=5,
            max_attempts=self.settings.communication_move_reconciliation_max_attempts,
        )

    async def reconcile(self, email_id: uuid.UUID) -> MessageMoveAttempt:
        """Inspect the immutable source ID; never repeat an ambiguous move."""
        attempt = await self.session.scalar(
            select(MessageMoveAttempt)
            .where(MessageMoveAttempt.email_id == email_id)
            .order_by(MessageMoveAttempt.attempt_number.desc())
        )
        if attempt is None:
            raise NotFoundError("Move attempt does not exist.")
        if attempt.status == MoveAttemptStatus.VERIFIED:
            return attempt
        email = await self.session.get(Email, email_id)
        mailbox = await self.session.get(Mailbox, email.mailbox_id) if email else None
        if email is None or mailbox is None:
            raise NotFoundError("Move reconciliation context is missing.")
        message = await GraphDraftClient(self.client.graph).get(
            mailbox.graph_user_id or mailbox.address, attempt.source_graph_message_id
        )
        if str(message.get("parentFolderId") or "") != attempt.destination_folder_id:
            attempt.status = MoveAttemptStatus.AMBIGUOUS
            attempt.error_code = "MOVE_RECONCILIATION_PENDING"
            attempt.error_message = "Immutable source message is not yet in the expected folder."
            await self.session.commit()
            raise StateConflictError("Move remains ambiguous; another bounded check is required.")
        attempt.status = MoveAttemptStatus.VERIFIED
        attempt.returned_graph_message_id = str(
            message.get("id") or attempt.source_graph_message_id
        )
        attempt.returned_parent_folder_id = attempt.destination_folder_id
        attempt.verified_at = utcnow()
        await CommunicationJobRepository(self.session).enqueue(
            job_type=CommunicationJobType.COMPLETE_EMAIL_WORKFLOW,
            idempotency_key=f"complete-after-move:{attempt.id}",
            email_id=email.id,
            task_id=attempt.task_id,
            priority=40,
            max_attempts=1,
        )
        await self.session.commit()
        return attempt

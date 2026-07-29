"""Bounded immutable-ID reconciliation after Graph accepts a send."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.communications.audit import add_system_communication_audit
from app.communications.enums import (
    CommunicationDraftStatus,
    CommunicationJobType,
    SendAttemptStatus,
)
from app.communications.hashes import recipient_set_hash, sha256_text
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import (
    COMMUNICATION_SEND_RECONCILIATION_DURATION_SECONDS,
    COMMUNICATION_SENT_COPY_VERIFIED_TOTAL,
)
from app.graph.client import GraphHttpClient
from app.graph.sent_items import SentItemsClient
from app.models import Mailbox, MailboxFolder, OutboundDraft, OutboundSendAttempt
from app.models.mixins import utcnow
from app.repositories.communication_jobs import CommunicationJobRepository
from app.services.graph_draft_service import _body, _recipients, graph_attachments_match


class SentReconciliationService:
    def __init__(self, session: AsyncSession, settings: Settings, graph: GraphHttpClient) -> None:
        self.session, self.settings, self.client = session, settings, SentItemsClient(graph)

    async def reconcile(self, draft_id: uuid.UUID) -> OutboundSendAttempt:
        draft = await self.session.get(OutboundDraft, draft_id)
        if draft is None or not draft.graph_draft_message_id:
            raise NotFoundError("Graph draft identity is missing.")
        attempt = await self.session.scalar(
            select(OutboundSendAttempt)
            .where(OutboundSendAttempt.outbound_draft_id == draft.id)
            .order_by(OutboundSendAttempt.attempt_number.desc())
        )
        mailbox = await self.session.get(Mailbox, draft.mailbox_id)
        sent_folder = await self.session.scalar(
            select(MailboxFolder).where(
                MailboxFolder.mailbox_id == draft.mailbox_id,
                MailboxFolder.display_name.ilike("Sent Items"),
            )
        )
        if attempt is None or mailbox is None or sent_folder is None:
            raise StateConflictError("Send attempt or Sent Items folder metadata is missing.")
        elapsed_seconds = max(0.0, (utcnow() - attempt.started_at).total_seconds())
        if elapsed_seconds > self.settings.communication_send_reconciliation_max_seconds:
            attempt.status = SendAttemptStatus.FAILED_REVIEW
            attempt.error_code = "SEND_RECONCILIATION_EXHAUSTED"
            attempt.error_message = "Send outcome requires explicit operator review."
            draft.draft_status = CommunicationDraftStatus.SEND_FAILED_REVIEW
            COMMUNICATION_SEND_RECONCILIATION_DURATION_SECONDS.observe(elapsed_seconds)
            add_system_communication_audit(
                self.session,
                entity_type="outbound_send_attempt",
                entity_id=attempt.id,
                action="send_reconciliation_window_exhausted",
                after={"status": attempt.status},
            )
            await self.session.commit()
            return attempt
        message = await self.client.inspect_immutable_message(
            mailbox.graph_user_id or mailbox.address, draft.graph_draft_message_id
        )
        attempt.reconciled_at = utcnow()
        if message.get("isDraft") is True:
            if attempt.status == SendAttemptStatus.AMBIGUOUS:
                draft.draft_status = CommunicationDraftStatus.SEND_AMBIGUOUS
                await self.session.commit()
                raise StateConflictError(
                    "Ambiguous send still appears as a draft; continue bounded reconciliation."
                )
            raise StateConflictError("Graph still reports a draft; do not resend automatically.")
        if str(message.get("parentFolderId") or "") != sent_folder.graph_folder_id:
            raise StateConflictError("Immutable message is not verified in shared Sent Items.")
        if not message.get("sentDateTime"):
            raise StateConflictError("Sent copy has no sentDateTime yet.")
        now = utcnow()
        attempt.status = SendAttemptStatus.SENT_COPY_VERIFIED
        attempt.sent_copy_verified_at = now
        attempt.sent_graph_message_id = str(message.get("id") or draft.graph_draft_message_id)
        attempt.sent_internet_message_id = str(message.get("internetMessageId") or "") or None
        attempt.sent_parent_folder_id = str(message.get("parentFolderId") or "")
        body_text, body_html = _body(message)
        attempt.sent_body_sha256 = sha256_text(
            f"{message.get('subject') or ''}\n{body_text or ''}\n{body_html or ''}"
        )
        attempt.sent_recipient_set_sha256 = recipient_set_hash(
            _recipients(message.get("toRecipients")),
            _recipients(message.get("ccRecipients")),
            _recipients(message.get("bccRecipients")),
        )
        attachments_match = await graph_attachments_match(
            self.session,
            self.client,
            mailbox.graph_user_id or mailbox.address,
            draft,
            graph_has_attachments=message.get("hasAttachments") is True,
        )
        attempt.sent_attachment_set_sha256 = (
            draft.attachment_set_sha256 if attachments_match else None
        )
        if (
            attempt.sent_body_sha256 != draft.body_sha256
            or attempt.sent_recipient_set_sha256 != draft.recipient_set_sha256
            or not attachments_match
        ):
            attempt.status = SendAttemptStatus.FAILED_REVIEW
            attempt.error_code = "SENT_COPY_SNAPSHOT_MISMATCH"
            attempt.error_message = "Sent copy does not match the approved snapshot."
            draft.draft_status = CommunicationDraftStatus.SEND_FAILED_REVIEW
            add_system_communication_audit(
                self.session,
                entity_type="outbound_send_attempt",
                entity_id=attempt.id,
                action="sent_copy_snapshot_mismatch",
                after={"status": attempt.status},
            )
            await self.session.commit()
            return attempt
        draft.draft_status = CommunicationDraftStatus.SENT_COPY_VERIFIED
        draft.delivery_status = "UNKNOWN"
        draft.sent_at = now
        COMMUNICATION_SEND_RECONCILIATION_DURATION_SECONDS.observe(elapsed_seconds)
        COMMUNICATION_SENT_COPY_VERIFIED_TOTAL.inc()
        await CommunicationJobRepository(self.session).enqueue(
            job_type=CommunicationJobType.MOVE_SOURCE_MESSAGE,
            idempotency_key=f"move-after-send:{attempt.id}",
            draft_id=draft.id,
            email_id=draft.email_id,
            task_id=draft.task_id,
            priority=30,
            max_attempts=self.settings.communication_move_job_max_attempts,
        )
        add_system_communication_audit(
            self.session,
            entity_type="outbound_send_attempt",
            entity_id=attempt.id,
            action="sent_copy_verified",
            after={"status": attempt.status},
            metadata={"draft_id": str(draft.id)},
        )
        await self.session.commit()
        return attempt

"""Email evidence ingestion: full message JSON, raw MIME, attachments.

Advances DISCOVERED -> FETCHED -> ATTACHMENTS_SAVED through the Milestone 1
atomic state-transition service. Never classifies, never sends, never moves.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import DomainError
from app.core.metrics import (
    GRAPH_ATTACHMENT_BYTES_TOTAL,
    GRAPH_ATTACHMENTS_DOWNLOADED_TOTAL,
)
from app.domain.enums import ActorType, AttachmentStatus, FolderMembership, ProcessingState
from app.evidence.base import EvidenceStore
from app.evidence.filenames import stored_attachment_filename
from app.evidence.filesystem import evidence_key_for_attachment, evidence_key_for_email
from app.graph.attachments import GraphAttachmentApi
from app.graph.errors import EvidenceLimitExceededError, GraphApiError
from app.graph.messages import GraphMessageApi
from app.jobs.service import GraphJobService
from app.models import Email, EmailAttachment, EmailProcessingEvent, EmailRecipient, Mailbox
from app.models.mixins import utcnow
from app.services.email_state import Actor, transition_email_state
from app.services.graph_subscriptions import mailbox_identifier
from app.services.prototype_import import parse_dt

logger = logging.getLogger(__name__)

TERMINAL_ATTACHMENT_STATUSES = frozenset(
    {
        AttachmentStatus.DOWNLOADED.value,
        AttachmentStatus.REFERENCE_NOT_DOWNLOADED.value,
        AttachmentStatus.QUARANTINED.value,
    }
)

_RECIPIENT_KEYS = {
    "toRecipients": "TO",
    "ccRecipients": "CC",
    "bccRecipients": "BCC",
    "replyTo": "REPLY_TO",
}


class IngestionPolicyViolation(DomainError):
    """Non-retryable policy failure that requires human review."""

    code = "ingestion_policy_violation"


class EmailIngestionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        message_api: GraphMessageApi,
        attachment_api: GraphAttachmentApi,
        store: EvidenceStore,
        *,
        worker_id: str,
    ) -> None:
        self.session = session
        self.settings = settings
        self.messages = message_api
        self.attachments = attachment_api
        self.store = store
        self.worker_id = worker_id
        self.actor = Actor(actor_type=ActorType.SYSTEM, actor_id=worker_id)
        self.jobs = GraphJobService(session, settings)

    async def ingest(self, email_id: uuid.UUID, *, job_id: uuid.UUID | None = None) -> str:
        email = await self.session.get(Email, email_id)
        if email is None:
            raise DomainError(f"Email {email_id} not found for ingestion.")
        mailbox = await self.session.get(Mailbox, email.mailbox_id)
        if mailbox is None:
            raise DomainError("Mailbox not found for ingestion.")

        state = ProcessingState(email.processing_state)

        if state == ProcessingState.FAILED_RETRYABLE:
            resume = ProcessingState(email.resume_state) if email.resume_state else None
            if resume not in (ProcessingState.DISCOVERED, ProcessingState.FETCHED):
                raise IngestionPolicyViolation(
                    "Email is not eligible for ingestion retry.",
                    details={"resume_state": email.resume_state},
                )
            await transition_email_state(
                self.session,
                email.id,
                resume,
                self.actor,
                "Ingestion retry resumed.",
                event_type="retry",
            )
            await self.session.refresh(email)
            state = ProcessingState(email.processing_state)

        if state not in (ProcessingState.DISCOVERED, ProcessingState.FETCHED):
            logger.info(
                "Email not eligible for ingestion; skipping",
                extra={
                    "extra_fields": {
                        "email_id": str(email.id),
                        "processing_state": state.value,
                    }
                },
            )
            return "skipped"

        if job_id is not None:
            email.ingestion_job_id = job_id

        try:
            if state == ProcessingState.DISCOVERED:
                await self._fetch_evidence(mailbox, email)
                state = ProcessingState.FETCHED
            await self._ingest_attachments(mailbox, email)
        except GraphApiError as exc:
            if exc.status_code == 404:
                await self._handle_message_gone(mailbox, email)
                return "message_gone"
            raise
        return "completed"

    # -------------------------------------------------------------- evidence

    async def _fetch_evidence(self, mailbox: Mailbox, email: Email) -> None:
        ident = mailbox_identifier(mailbox)
        payload = await self.messages.get_full_message(ident, email.graph_message_id)

        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        json_result = await self.store.put_bytes(
            evidence_key_for_email(str(mailbox.id), str(email.id), "message.json"),
            canonical,
            content_type="application/json",
        )
        mime_result = await self.messages.download_mime(
            ident,
            email.graph_message_id,
            self.store,
            evidence_key_for_email(str(mailbox.id), str(email.id), "message.eml"),
            max_bytes=self.settings.max_raw_mime_bytes,
        )

        self._apply_message_metadata(email, payload)
        email.full_message_json_storage_uri = json_result.storage_uri
        email.full_message_json_sha256 = json_result.sha256_checksum
        email.raw_mime_storage_uri = mime_result.storage_uri
        email.raw_mime_sha256 = mime_result.sha256_checksum
        email.evidence_saved_at = utcnow()
        await self._replace_recipients(email, payload)
        await self.session.commit()

        await transition_email_state(
            self.session,
            email.id,
            ProcessingState.FETCHED,
            self.actor,
            "Full Graph message and raw MIME evidence saved.",
            metadata={
                "full_message_json_storage_uri": json_result.storage_uri,
                "full_message_json_sha256": json_result.sha256_checksum,
                "raw_mime_storage_uri": mime_result.storage_uri,
                "raw_mime_sha256": mime_result.sha256_checksum,
                "raw_mime_bytes": mime_result.bytes_written,
            },
        )
        await self.session.refresh(email)

    def _apply_message_metadata(self, email: Email, payload: dict[str, Any]) -> None:
        sender = (payload.get("from") or {}).get("emailAddress") or {}
        body = payload.get("body") or {}
        email.subject = payload.get("subject", email.subject)
        email.sender_name = sender.get("name", email.sender_name)
        if sender.get("address"):
            email.sender_email = str(sender["address"]).lower()
        email.received_at = parse_dt(payload.get("receivedDateTime")) or email.received_at
        email.sent_at = parse_dt(payload.get("sentDateTime")) or email.sent_at
        email.body_content_type = body.get("contentType", email.body_content_type)
        content = body.get("content")
        if content is not None:
            if (body.get("contentType") or "").lower() == "html":
                email.body_html = content
            else:
                email.body_text = content
        email.body_preview = payload.get("bodyPreview", email.body_preview)
        email.has_attachments = bool(payload.get("hasAttachments", email.has_attachments))
        email.is_read = payload.get("isRead", email.is_read)
        email.conversation_id = payload.get("conversationId", email.conversation_id)
        email.internet_message_id = payload.get("internetMessageId", email.internet_message_id)
        email.current_graph_folder_id = payload.get("parentFolderId", email.current_graph_folder_id)
        email.last_graph_modified_at = parse_dt(payload.get("lastModifiedDateTime"))
        email.fetched_at = email.fetched_at or utcnow()

    async def _replace_recipients(self, email: Email, payload: dict[str, Any]) -> None:
        # Replays replace the whole recipient set idempotently.
        await self.session.execute(
            delete(EmailRecipient).where(EmailRecipient.email_id == email.id)
        )
        for graph_key, recipient_type in _RECIPIENT_KEYS.items():
            for ordinal, entry in enumerate(payload.get(graph_key) or []):
                address = ((entry or {}).get("emailAddress") or {}).get("address")
                if not address:
                    continue
                self.session.add(
                    EmailRecipient(
                        email_id=email.id,
                        recipient_type=recipient_type,
                        display_name=((entry or {}).get("emailAddress") or {}).get("name"),
                        address=str(address).lower(),
                        ordinal=ordinal,
                    )
                )

    # ------------------------------------------------------------ attachments

    async def _ingest_attachments(self, mailbox: Mailbox, email: Email) -> None:
        ident = mailbox_identifier(mailbox)

        if not email.has_attachments:
            items: list[dict[str, Any]] = []
        else:
            items = await self.attachments.list_attachments(ident, email.graph_message_id)

        if len(items) > self.settings.max_attachments_per_message:
            await self._fail_review(
                email,
                error_code="attachment_count_exceeded",
                error_message=(
                    f"Message has {len(items)} attachments; policy allows "
                    f"{self.settings.max_attachments_per_message}."
                ),
            )
            return

        for item in items:
            await self._ingest_one_attachment(mailbox, email, item)
        await self.session.commit()

        statuses = (
            await self.session.scalars(
                select(EmailAttachment.status).where(EmailAttachment.email_id == email.id)
            )
        ).all()
        if all(s in TERMINAL_ATTACHMENT_STATUSES for s in statuses):
            await transition_email_state(
                self.session,
                email.id,
                ProcessingState.ATTACHMENTS_SAVED,
                self.actor,
                f"Attachment ingestion completed. {len(statuses)} attachment(s).",
                metadata={"attachment_count": len(statuses)},
            )
            if self.settings.classification_enabled and self.settings.classification_auto_enqueue:
                await GraphJobService(self.session, self.settings).enqueue_classify_email(
                    mailbox_id=email.mailbox_id,
                    email_id=email.id,
                    reason="evidence ingestion completed",
                )
                await self.session.commit()
        else:
            raise DomainError(
                "Attachments still pending after ingestion round.",
                details={"email_id": str(email.id)},
            )

    async def _ingest_one_attachment(
        self, mailbox: Mailbox, email: Email, item: dict[str, Any]
    ) -> None:
        graph_attachment_id = item.get("id")
        if not graph_attachment_id:
            return
        existing = await self.session.scalar(
            select(EmailAttachment).where(
                EmailAttachment.email_id == email.id,
                EmailAttachment.graph_attachment_id == graph_attachment_id,
            )
        )
        if existing is not None and existing.status in TERMINAL_ATTACHMENT_STATUSES:
            return  # replay: already terminal

        odata_type = str(item.get("@odata.type") or "#microsoft.graph.fileAttachment")
        content_type = item.get("contentType")
        size = int(item.get("size") or 0)
        attachment = existing or EmailAttachment(
            id=uuid.uuid4(),
            email_id=email.id,
            graph_attachment_id=graph_attachment_id,
            status=AttachmentStatus.DISCOVERED.value,
        )
        attachment.attachment_type = odata_type
        attachment.original_filename = item.get("name")
        attachment.mime_type = content_type
        attachment.graph_size_bytes = size or None
        attachment.is_inline = bool(item.get("isInline"))
        attachment.content_id = item.get("contentId")
        if existing is None:
            self.session.add(attachment)
        await self.session.flush()

        stored_name = stored_attachment_filename(str(attachment.id), item.get("name"))
        attachment.stored_filename = stored_name

        if odata_type.endswith("referenceAttachment"):
            attachment.status = AttachmentStatus.REFERENCE_NOT_DOWNLOADED.value
            return

        if size > self.settings.max_attachment_bytes:
            attachment.status = AttachmentStatus.QUARANTINED.value
            attachment.storage_uri = None
            logger.warning(
                "Attachment quarantined: exceeds size policy",
                extra={
                    "extra_fields": {
                        "email_id": str(email.id),
                        "attachment_id": str(attachment.id),
                        "graph_size_bytes": size,
                    }
                },
            )
            return

        if (
            content_type
            and content_type.lower()
            not in {m.lower() for m in self.settings.allowed_attachment_mime_types}
            and self.settings.quarantine_unknown_attachments
        ):
            attachment.status = AttachmentStatus.QUARANTINED.value
            logger.warning(
                "Attachment quarantined: content type not allowed",
                extra={
                    "extra_fields": {
                        "email_id": str(email.id),
                        "attachment_id": str(attachment.id),
                        "content_type": content_type,
                    }
                },
            )
            return

        ident = mailbox_identifier(mailbox)
        key = evidence_key_for_attachment(str(mailbox.id), str(email.id), stored_name)
        try:
            if odata_type.endswith("itemAttachment"):
                payload = await self.attachments.get_item_attachment(
                    ident, email.graph_message_id, graph_attachment_id
                )
                data = json.dumps(payload, sort_keys=True).encode("utf-8")
                result = await self.store.put_bytes(
                    key + ".item.json", data, content_type="application/json"
                )
            else:
                result = await self.attachments.download_file_attachment(
                    ident,
                    email.graph_message_id,
                    graph_attachment_id,
                    self.store,
                    key,
                    max_bytes=self.settings.max_attachment_bytes,
                    content_type=content_type,
                )
        except EvidenceLimitExceededError:
            attachment.status = AttachmentStatus.QUARANTINED.value
            attachment.storage_uri = None
            return

        attachment.storage_uri = result.storage_uri
        attachment.sha256_checksum = result.sha256_checksum
        attachment.stored_size_bytes = result.bytes_written
        attachment.status = AttachmentStatus.DOWNLOADED.value
        attachment.downloaded_at = utcnow()
        GRAPH_ATTACHMENTS_DOWNLOADED_TOTAL.inc()
        GRAPH_ATTACHMENT_BYTES_TOTAL.inc(result.bytes_written)

    # ---------------------------------------------------------------- failure

    async def _fail_review(self, email: Email, *, error_code: str, error_message: str) -> None:
        await transition_email_state(
            self.session,
            email.id,
            ProcessingState.FAILED_REVIEW,
            self.actor,
            "Ingestion policy violation requires human review.",
            error_code=error_code,
            error_message=error_message,
        )

    async def _handle_message_gone(self, mailbox: Mailbox, email: Email) -> None:
        """The source message returned 404 between discovery and ingestion.

        Delta is the authority: schedule a folder sync so membership gets
        refreshed, record the failure, and route to FAILED_REVIEW rather than
        retrying forever.
        """
        now = utcnow()
        email.synced_folder_membership = FolderMembership.UNKNOWN.value
        self.session.add(
            EmailProcessingEvent(
                email_id=email.id,
                from_state=email.processing_state,
                to_state=email.processing_state,
                event_type="source_message_gone",
                note="Graph returned 404 for the source message during ingestion.",
                occurred_at=now,
            )
        )
        folder_row = None
        if email.current_graph_folder_id:
            from app.models import MailboxFolder

            folder_row = await self.session.scalar(
                select(MailboxFolder).where(
                    MailboxFolder.mailbox_id == mailbox.id,
                    MailboxFolder.graph_folder_id == email.current_graph_folder_id,
                )
            )
        if folder_row is not None:
            await self.jobs.enqueue_sync_folder(
                mailbox_id=mailbox.id,
                folder_id=folder_row.id,
                reason="INGESTION_404",
                idempotency_key=f"sync-404:{email.id}",
            )
        await self.session.commit()
        await self._fail_review(
            email,
            error_code="message_not_retrievable",
            error_message="Source message was no longer retrievable (HTTP 404).",
        )

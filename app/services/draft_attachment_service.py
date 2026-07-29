"""Select only approved, active, current, hash-valid controlled documents."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.communications.attachments import transmission_blockers
from app.communications.audit import add_communication_audit
from app.communications.enums import CommunicationDraftStatus
from app.communications.snapshots import create_version, invalidate_approval
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import (
    COMMUNICATION_ATTACHMENT_BYTES_TOTAL,
    COMMUNICATION_ATTACHMENTS_SELECTED_TOTAL,
)
from app.models import Document, DocumentVersion, OutboundDraft, OutboundDraftAttachment
from app.models.mixins import utcnow


class DraftAttachmentService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings

    async def select(
        self,
        draft_id: uuid.UUID,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        actor: CurrentActor,
        *,
        expected_revision: int,
        expected_graph_change_key: str | None,
        expected_graph_etag: str | None,
    ) -> OutboundDraftAttachment:
        if not self.settings.communication_attachments_enabled:
            raise StateConflictError("Communication attachments are disabled.")
        draft = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.id == draft_id).with_for_update()
        )
        document = await self.session.get(Document, document_id)
        version = await self.session.get(DocumentVersion, version_id)
        if (
            draft is None
            or document is None
            or version is None
            or version.document_id != document.id
        ):
            raise NotFoundError("Controlled document version does not exist.")
        self._assert_expected(
            draft,
            expected_revision,
            expected_graph_change_key,
            expected_graph_etag,
        )
        self._assert_mutable(draft)
        duplicate = await self.session.scalar(
            select(OutboundDraftAttachment.id).where(
                OutboundDraftAttachment.outbound_draft_id == draft.id,
                OutboundDraftAttachment.document_version_id == version.id,
                OutboundDraftAttachment.removed_at.is_(None),
            )
        )
        if duplicate:
            raise StateConflictError("This controlled document version is already selected.")
        blockers = transmission_blockers(document, version)
        if blockers:
            raise StateConflictError(
                "Document cannot be transmitted.", details={"blockers": blockers}
            )
        existing_total = await self.session.scalar(
            select(func.coalesce(func.sum(OutboundDraftAttachment.size_bytes), 0)).where(
                OutboundDraftAttachment.outbound_draft_id == draft.id,
                OutboundDraftAttachment.removed_at.is_(None),
            )
        )
        total = int(existing_total or 0) + version.size_bytes
        if total > self.settings.communication_total_attachment_max_bytes:
            raise StateConflictError("Attachment set exceeds the configured safe size.")
        if version.size_bytes > self.settings.communication_large_attachment_max_bytes:
            raise StateConflictError("Attachment exceeds the configured per-file size limit.")
        if version.size_bytes > self.settings.communication_simple_attachment_max_bytes and not (
            self.settings.communication_large_attachments_enabled
            and self.settings.communication_shared_mailbox_large_attachment_accepted
        ):
            raise StateConflictError("Large shared-mailbox attachments are not accepted.")
        row = OutboundDraftAttachment(
            outbound_draft_id=draft.id,
            document_id=document.id,
            document_version_id=version.id,
            filename=version.filename,
            mime_type=version.mime_type,
            size_bytes=version.size_bytes,
            content_sha256=version.content_sha256,
            status="VALIDATED",
            upload_method=(
                "SIMPLE"
                if version.size_bytes <= self.settings.communication_simple_attachment_max_bytes
                else "UPLOAD_SESSION"
            ),
            added_by_actor=actor.actor_id,
            added_at=utcnow(),
        )
        self.session.add(row)
        await self.session.flush()
        await invalidate_approval(self.session, draft, "attachment set changed")
        await create_version(
            self.session, draft, actor_id=actor.actor_id, change_reason="attachment selected"
        )
        draft.draft_status = CommunicationDraftStatus.REVIEW_IN_PROGRESS
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="outbound_draft_attachment",
            entity_id=row.id,
            action="controlled_attachment_selected",
            after={"size_bytes": row.size_bytes, "status": row.status},
            metadata={"draft_id": str(draft.id), "document_version_id": str(version.id)},
        )
        await self.session.commit()
        COMMUNICATION_ATTACHMENTS_SELECTED_TOTAL.inc()
        COMMUNICATION_ATTACHMENT_BYTES_TOTAL.inc(version.size_bytes)
        return row

    async def remove(
        self,
        draft_id: uuid.UUID,
        attachment_id: uuid.UUID,
        actor: CurrentActor,
        *,
        expected_revision: int,
        expected_graph_change_key: str | None,
        expected_graph_etag: str | None,
    ) -> None:
        draft = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.id == draft_id).with_for_update()
        )
        row = await self.session.get(OutboundDraftAttachment, attachment_id)
        if draft is None or row is None or row.outbound_draft_id != draft.id:
            raise NotFoundError("Draft attachment does not exist.")
        self._assert_expected(
            draft,
            expected_revision,
            expected_graph_change_key,
            expected_graph_etag,
        )
        self._assert_mutable(draft)
        row.status = "REMOVED"
        row.removed_at = utcnow()
        await invalidate_approval(self.session, draft, "attachment removed")
        await create_version(
            self.session, draft, actor_id=actor.actor_id, change_reason="attachment removed"
        )
        draft.draft_status = CommunicationDraftStatus.REVIEW_IN_PROGRESS
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="outbound_draft_attachment",
            entity_id=row.id,
            action="draft_attachment_removed",
            after={"status": row.status},
            metadata={"draft_id": str(draft.id)},
        )
        await self.session.commit()

    @staticmethod
    def _assert_expected(
        draft: OutboundDraft,
        expected_revision: int,
        expected_graph_change_key: str | None,
        expected_graph_etag: str | None,
    ) -> None:
        if draft.local_revision != expected_revision:
            raise StateConflictError(
                "Draft revision changed.",
                details={"current_revision": draft.local_revision},
            )
        if draft.graph_draft_message_id and (
            draft.graph_change_key != expected_graph_change_key
            or draft.graph_etag != expected_graph_etag
        ):
            raise StateConflictError(
                "Graph draft changed; synchronize before changing attachments."
            )

    @staticmethod
    def _assert_mutable(draft: OutboundDraft) -> None:
        if draft.draft_status in {
            CommunicationDraftStatus.SEND_QUEUED,
            CommunicationDraftStatus.SENDING,
            CommunicationDraftStatus.SEND_ACCEPTED,
            CommunicationDraftStatus.SEND_AMBIGUOUS,
            CommunicationDraftStatus.SENT_COPY_VERIFIED,
            CommunicationDraftStatus.CANCELLED,
        }:
            raise StateConflictError("A queued, sending, sent, or cancelled draft cannot change.")

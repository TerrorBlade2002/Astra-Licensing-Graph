"""Upload validated governed documents to a Graph draft."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.communications.attachments import transmission_blockers
from app.communications.audit import add_communication_audit
from app.communications.enums import CommunicationDraftStatus
from app.communications.snapshots import create_version, invalidate_approval
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.graph.client import GraphHttpClient
from app.graph.draft_attachments import GraphDraftAttachmentClient
from app.graph.drafts import GraphDraftClient
from app.graph.errors import GraphApiError
from app.models import (
    Document,
    DocumentVersion,
    Mailbox,
    OutboundDraft,
    OutboundDraftAttachment,
)
from app.models.mixins import utcnow


class GraphDraftAttachmentService:
    def __init__(self, session: AsyncSession, settings: Settings, graph: GraphHttpClient) -> None:
        self.session, self.settings, self.graph = session, settings, graph

    async def upload_pending(self, draft_id: uuid.UUID, actor: CurrentActor) -> int:
        draft = await self.session.get(OutboundDraft, draft_id)
        if draft is None or not draft.graph_draft_message_id:
            raise NotFoundError("Graph draft does not exist.")
        mailbox = await self.session.get(Mailbox, draft.mailbox_id)
        if mailbox is None:
            raise NotFoundError("Mailbox does not exist.")
        rows = list(
            await self.session.scalars(
                select(OutboundDraftAttachment).where(
                    OutboundDraftAttachment.outbound_draft_id == draft.id,
                    OutboundDraftAttachment.status == "VALIDATED",
                    OutboundDraftAttachment.removed_at.is_(None),
                )
            )
        )
        client = GraphDraftAttachmentClient(self.graph)
        uploaded = 0
        for row in rows:
            if not row.document_id or not row.document_version_id:
                raise StateConflictError("Raw inbound evidence cannot be attached directly.")
            document = await self.session.get(Document, row.document_id)
            version = await self.session.get(DocumentVersion, row.document_version_id)
            if document is None or version is None:
                raise StateConflictError("Attachment eligibility changed before upload.")
            matching_existing = [
                item
                for item in await GraphDraftClient(self.graph).attachments(
                    mailbox.graph_user_id or mailbox.address,
                    draft.graph_draft_message_id,
                )
                if str(item.get("name") or "") == row.filename
                and int(item.get("size") or 0) == row.size_bytes
                and not item.get("isInline")
            ]
            if matching_existing:
                # This may be a prior upload whose response/commit was lost, or
                # an Outlook-added file. Metadata cannot prove the content hash,
                # so never create a possible duplicate and never auto-adopt it.
                row.status = "FAILED_REVIEW"
                await self.session.commit()
                raise StateConflictError(
                    "Graph already contains an untracked matching attachment; "
                    "explicit hash review is required."
                )
            blockers = transmission_blockers(document, version, today=date.today())
            if blockers:
                row.status = "FAILED_REVIEW"
                await self.session.commit()
                raise StateConflictError(
                    "Attachment eligibility changed before upload.",
                    details={"blockers": blockers},
                )
            url = self.graph.build_url(
                f"sites/{quote(version.graph_site_id, safe='')}/drives/"
                f"{quote(version.graph_drive_id, safe='')}/items/"
                f"{quote(version.graph_drive_item_id, safe='')}/content"
            )
            content = await self.graph.download_bytes(
                url, max_bytes=self.settings.communication_large_attachment_max_bytes
            )
            if hashlib.sha256(content).hexdigest() != row.content_sha256:
                row.status = "FAILED_REVIEW"
                await self.session.commit()
                raise StateConflictError("Attachment hash changed before transmission.")
            if row.upload_method == "UPLOAD_SESSION":
                if not (
                    self.settings.communication_large_attachments_enabled
                    and self.settings.communication_shared_mailbox_large_attachment_accepted
                ):
                    raise StateConflictError("Large shared-mailbox attachment path is disabled.")
                result = await client.upload_large(
                    mailbox.graph_user_id or mailbox.address,
                    draft.graph_draft_message_id,
                    filename=row.filename,
                    content=content,
                    chunk_bytes=self.settings.communication_upload_chunk_bytes,
                )
            else:
                try:
                    result = await client.add_small(
                        mailbox.graph_user_id or mailbox.address,
                        draft.graph_draft_message_id,
                        filename=row.filename,
                        mime_type=row.mime_type or "application/octet-stream",
                        content=content,
                    )
                except (httpx.TimeoutException, httpx.ReadError, httpx.WriteError):
                    result = await self._reconcile_ambiguous_small_attachment(
                        mailbox.graph_user_id or mailbox.address, draft, row
                    )
                except GraphApiError as exc:
                    if exc.status_code not in {408, 500, 502, 503, 504}:
                        raise
                    result = await self._reconcile_ambiguous_small_attachment(
                        mailbox.graph_user_id or mailbox.address, draft, row
                    )
            row.graph_attachment_id = str(result.get("id") or "")
            if not row.graph_attachment_id:
                raise StateConflictError("Graph did not return an attachment identifier.")
            row.status = "GRAPH_UPLOADED"
            row.graph_uploaded_at = utcnow()
            uploaded += 1
        if uploaded:
            await invalidate_approval(self.session, draft, "Graph attachment set changed")
            await create_version(
                self.session,
                draft,
                actor_id=actor.actor_id,
                change_reason="attachments synchronized to Graph",
            )
        await self.session.commit()
        return uploaded

    async def remove_uploaded(
        self,
        draft_id: uuid.UUID,
        attachment_id: uuid.UUID,
        *,
        expected_revision: int,
        expected_graph_change_key: str | None,
        expected_graph_etag: str | None,
        actor: CurrentActor,
    ) -> bool:
        draft = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.id == draft_id).with_for_update()
        )
        row = await self.session.get(OutboundDraftAttachment, attachment_id)
        if draft is None or row is None or row.outbound_draft_id != draft.id:
            raise NotFoundError("Draft attachment does not exist.")
        if draft.local_revision != expected_revision or (
            draft.graph_draft_message_id
            and (
                draft.graph_change_key != expected_graph_change_key
                or draft.graph_etag != expected_graph_etag
            )
        ):
            raise StateConflictError("Draft changed before attachment removal.")
        if draft.draft_status in {
            CommunicationDraftStatus.SEND_QUEUED,
            CommunicationDraftStatus.SENDING,
            CommunicationDraftStatus.SEND_ACCEPTED,
            CommunicationDraftStatus.SEND_AMBIGUOUS,
            CommunicationDraftStatus.SENT_COPY_VERIFIED,
            CommunicationDraftStatus.CANCELLED,
        }:
            raise StateConflictError("A queued, sending, sent, or cancelled draft cannot change.")
        if not row.graph_attachment_id:
            return False
        if not draft.graph_draft_message_id:
            raise StateConflictError("Graph attachment exists without a Graph draft identity.")
        if draft.draft_status in {
            CommunicationDraftStatus.PENDING_SEND_APPROVAL,
            CommunicationDraftStatus.APPROVED_TO_SEND,
        }:
            await invalidate_approval(
                self.session,
                draft,
                "attachment removal started before Graph mutation",
            )
            draft.draft_status = CommunicationDraftStatus.CHANGES_REQUESTED
            add_communication_audit(
                self.session,
                actor=actor,
                entity_type="outbound_draft",
                entity_id=draft.id,
                action="approval_invalidated_before_graph_attachment_removal",
                after={"status": draft.draft_status},
            )
            await self.session.commit()
        mailbox = await self.session.get(Mailbox, draft.mailbox_id)
        if mailbox is None:
            raise NotFoundError("Mailbox does not exist.")
        mailbox_identity = mailbox.graph_user_id or mailbox.address
        graph_draft_id = draft.graph_draft_message_id
        graph_attachment_id = row.graph_attachment_id
        assert graph_draft_id is not None and graph_attachment_id is not None
        # Do not hold a database transaction while Graph performs the
        # idempotent attachment-ID deletion.
        await self.session.rollback()
        try:
            await GraphDraftAttachmentClient(self.graph).remove(
                mailbox_identity,
                graph_draft_id,
                graph_attachment_id,
            )
        except GraphApiError as exc:
            if exc.status_code != 404:
                raise
        return True

    async def _reconcile_ambiguous_small_attachment(
        self,
        mailbox: str,
        draft: OutboundDraft,
        row: OutboundDraftAttachment,
    ) -> dict[str, object]:
        candidates = [
            item
            for item in await GraphDraftClient(self.graph).attachments(
                mailbox, draft.graph_draft_message_id or ""
            )
            if str(item.get("name") or "") == row.filename
            and int(item.get("size") or 0) == row.size_bytes
            and not item.get("isInline")
        ]
        if len(candidates) == 1 and candidates[0].get("id"):
            return candidates[0]
        row.status = "FAILED_REVIEW"
        await self.session.commit()
        raise StateConflictError(
            "Small attachment upload outcome is ambiguous; explicit review is required."
        )

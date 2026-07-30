"""Graph reply-draft creation and Outlook-side edit reconciliation."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.communications.audit import add_communication_audit
from app.communications.enums import CommunicationDraftStatus, CommunicationJobType, RecipientMode
from app.communications.hashes import recipient_set_hash, sha256_text
from app.communications.snapshots import create_version, invalidate_approval
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.graph.client import GraphHttpClient
from app.graph.drafts import GraphDraftClient
from app.graph.errors import GraphApiError
from app.models import Email, Mailbox, OutboundDraft, OutboundDraftAttachment, ResponsePlan
from app.models.mixins import utcnow
from app.repositories.communication_jobs import CommunicationJobRepository


def _recipients(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        email = item.get("emailAddress", {}) if isinstance(item, dict) else {}
        if isinstance(email, dict) and email.get("address"):
            result.append(
                {"address": str(email["address"]).lower(), "name": str(email.get("name") or "")}
            )
    return result


def _graph_recipients(value: list[dict[str, Any]]) -> list[dict[str, dict[str, str]]]:
    return [
        {
            "emailAddress": {
                "address": str(item.get("address") or ""),
                "name": str(item.get("name") or ""),
            }
        }
        for item in value
    ]


def _body(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    body = payload.get("body")
    if not isinstance(body, dict):
        return None, None
    content = str(body.get("content") or "")
    return (
        (None, content) if str(body.get("contentType") or "").lower() == "html" else (content, None)
    )


def _attachment_identities(rows: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
    return sorted(
        (
            str(row.get("id") or ""),
            str(row.get("name") or ""),
            int(row.get("size") or 0),
        )
        for row in rows
        if not row.get("isInline")
    )


async def graph_attachments_match(
    session: AsyncSession,
    client: GraphDraftClient,
    mailbox: str,
    draft: OutboundDraft,
    *,
    graph_has_attachments: bool,
) -> bool:
    local = list(
        await session.scalars(
            select(OutboundDraftAttachment).where(
                OutboundDraftAttachment.outbound_draft_id == draft.id,
                OutboundDraftAttachment.removed_at.is_(None),
            )
        )
    )
    if not graph_has_attachments and not local:
        return True
    actual = _attachment_identities(
        await client.attachments(mailbox, draft.graph_draft_message_id or "")
    )
    expected = sorted(
        (row.graph_attachment_id or "", row.filename, row.size_bytes)
        for row in local
        if row.status == "GRAPH_UPLOADED"
    )
    return len(expected) == len(local) and actual == expected


class GraphDraftService:
    def __init__(self, session: AsyncSession, settings: Settings, graph: GraphHttpClient) -> None:
        self.session, self.settings, self.client = session, settings, GraphDraftClient(graph)

    async def _context(
        self, draft_id: uuid.UUID
    ) -> tuple[OutboundDraft, ResponsePlan, Email, Mailbox]:
        draft = await self.session.get(OutboundDraft, draft_id)
        if draft is None or draft.response_plan_id is None or draft.email_id is None:
            raise NotFoundError("Controlled draft does not exist.")
        plan = await self.session.get(ResponsePlan, draft.response_plan_id)
        email = await self.session.get(Email, draft.email_id)
        mailbox = await self.session.get(Mailbox, draft.mailbox_id)
        if plan is None or email is None or mailbox is None:
            raise NotFoundError("Draft source context is incomplete.")
        return draft, plan, email, mailbox

    async def create(self, draft_id: uuid.UUID, actor: CurrentActor) -> OutboundDraft:
        if (
            not self.settings.communications_enabled
            or not self.settings.graph_draft_creation_enabled
        ):
            raise StateConflictError("Graph draft creation is disabled.")
        draft, plan, email, mailbox = await self._context(draft_id)
        if draft.graph_draft_message_id:
            await self.session.commit()
            if draft.draft_status == CommunicationDraftStatus.GRAPH_DRAFT_PENDING:
                return await self._finalize(draft, plan, mailbox, actor)
            return draft
        if draft.draft_status == CommunicationDraftStatus.GRAPH_DRAFT_PENDING:
            await self.session.rollback()
            raise StateConflictError(
                "Graph draft creation outcome is unresolved; reconcile before recreating."
            )
        if plan.proposed_recipient_mode == RecipientMode.REPLY_ALL and (
            not self.settings.communication_reply_all_enabled or not plan.reply_all_reviewed
        ):
            raise StateConflictError("Reply-all was not explicitly reviewed.")
        mailbox_identity = mailbox.graph_user_id or mailbox.address
        source_message_id = email.graph_message_id
        # Release the read transaction before the source-message Graph check.
        # The draft row is locked and revalidated immediately before intent.
        await self.session.rollback()
        source = await self.client.get(mailbox_identity, source_message_id)
        if not source.get("id") or source.get("isDraft") is True:
            raise StateConflictError("Source message is missing or is itself a draft.")
        locked_draft = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.id == draft_id).with_for_update()
        )
        if locked_draft is None or locked_draft.response_plan_id is None:
            raise NotFoundError("Controlled draft does not exist.")
        locked_plan = await self.session.get(ResponsePlan, locked_draft.response_plan_id)
        locked_mailbox = await self.session.get(Mailbox, locked_draft.mailbox_id)
        if locked_plan is None or locked_mailbox is None:
            raise NotFoundError("Draft source context is incomplete.")
        draft, plan, mailbox = locked_draft, locked_plan, locked_mailbox
        mailbox_identity = mailbox.graph_user_id or mailbox.address
        if draft.graph_draft_message_id:
            await self.session.commit()
            if draft.draft_status == CommunicationDraftStatus.GRAPH_DRAFT_PENDING:
                return await self._finalize(draft, plan, mailbox, actor)
            return draft
        if draft.draft_status == CommunicationDraftStatus.GRAPH_DRAFT_PENDING:
            await self.session.rollback()
            raise StateConflictError(
                "Graph draft creation outcome is unresolved; reconcile before recreating."
            )
        if plan.proposed_recipient_mode == RecipientMode.REPLY_ALL and (
            not self.settings.communication_reply_all_enabled or not plan.reply_all_reviewed
        ):
            await self.session.rollback()
            raise StateConflictError("Reply-all was not explicitly reviewed.")
        draft.draft_status = CommunicationDraftStatus.GRAPH_DRAFT_PENDING
        await self.session.commit()  # persist intent before the non-idempotent create call
        try:
            created = await self.client.create_reply(
                mailbox_identity,
                source_message_id,
                reply_all=plan.proposed_recipient_mode == RecipientMode.REPLY_ALL,
            )
        except (httpx.TransportError, httpx.TimeoutException):
            # The createReply request is not replayed when the transport cannot
            # prove whether Graph created a draft.
            await self._enqueue_create_reconciliation(draft)
            raise StateConflictError(
                "Graph draft creation outcome is ambiguous; reconcile before recreating."
            ) from None
        except GraphApiError as exc:
            if exc.status_code in {408, 500, 502, 503, 504}:
                await self._enqueue_create_reconciliation(draft)
                raise StateConflictError(
                    "Graph draft creation outcome is ambiguous; reconcile before recreating."
                ) from None
            draft.draft_status = CommunicationDraftStatus.SEND_FAILED_REVIEW
            await self.session.commit()
            raise StateConflictError("Graph rejected reply-draft creation.") from None
        graph_id = str(created["id"])
        draft.graph_draft_message_id = graph_id
        await self.session.commit()  # retain immutable identity before follow-up retrieval
        try:
            return await self._finalize(draft, plan, mailbox, actor)
        except (httpx.TransportError, httpx.TimeoutException, GraphApiError):
            await self._enqueue_create_reconciliation(draft)
            raise StateConflictError(
                "Graph draft exists but final synchronization needs reconciliation."
            ) from None

    async def _enqueue_create_reconciliation(self, draft: OutboundDraft) -> None:
        await CommunicationJobRepository(self.session).enqueue(
            job_type=CommunicationJobType.RECONCILE_GRAPH_DRAFT,
            idempotency_key=f"ambiguous-graph-draft:{draft.id}:{draft.local_revision}",
            draft_id=draft.id,
            email_id=draft.email_id,
            task_id=draft.task_id,
            priority=5,
            max_attempts=self.settings.communication_send_reconciliation_max_attempts,
        )
        await self.session.commit()

    async def _finalize(
        self,
        draft: OutboundDraft,
        plan: ResponsePlan,
        mailbox: Mailbox,
        actor: CurrentActor,
    ) -> OutboundDraft:
        """Patch a known immutable Graph draft to the reviewed local content."""
        if not draft.graph_draft_message_id:
            raise StateConflictError("Graph draft identity is not known.")
        mailbox_identity = mailbox.graph_user_id or mailbox.address
        actual = await self.client.get(mailbox_identity, draft.graph_draft_message_id)
        if actual.get("isDraft") is not True:
            await self._mark_no_longer_draft(draft)
            raise StateConflictError("Graph message is no longer a draft; reconciliation queued.")
        graph_to = _recipients(actual.get("toRecipients"))
        graph_cc = _recipients(actual.get("ccRecipients"))
        graph_bcc = _recipients(actual.get("bccRecipients"))
        draft.reply_to_recipients = _recipients(actual.get("replyTo"))
        changes: dict[str, Any] = {
            "subject": draft.subject,
            "body": {
                "contentType": "HTML" if draft.body_html else "Text",
                "content": draft.body_html or draft.body_text or "",
            },
        }
        if plan.proposed_recipient_mode in {RecipientMode.MANUAL, RecipientMode.INTERNAL_FORWARD}:
            changes |= {
                "toRecipients": _graph_recipients(draft.to_recipients),
                "ccRecipients": _graph_recipients(draft.cc_recipients),
            }
            if plan.bcc_authorized:
                changes["bccRecipients"] = _graph_recipients(draft.bcc_recipients)
        else:
            # Graph is authoritative for the initial reply recipient. Persist it
            # before applying the reviewed body.
            draft.to_recipients = graph_to
            draft.cc_recipients = graph_cc
            draft.bcc_recipients = graph_bcc
        await self.client.patch(
            mailbox_identity,
            draft.graph_draft_message_id,
            changes,
            etag=str(actual.get("@odata.etag") or "") or None,
        )
        final = await self.client.get(mailbox_identity, draft.graph_draft_message_id)
        if final.get("isDraft") is not True:
            await self._mark_no_longer_draft(draft)
            raise StateConflictError("Graph message is no longer a draft; reconciliation queued.")
        draft.to_recipients = _recipients(final.get("toRecipients"))
        draft.cc_recipients = _recipients(final.get("ccRecipients"))
        draft.bcc_recipients = _recipients(final.get("bccRecipients"))
        draft.graph_change_key = str(final.get("changeKey") or "") or None
        draft.graph_etag = str(final.get("@odata.etag") or "") or None
        draft.graph_parent_folder_id = str(final.get("parentFolderId") or "") or None
        draft.graph_web_link = str(final.get("webLink") or "") or None
        draft.graph_draft_created_at = utcnow()
        draft.graph_last_synced_at = utcnow()
        draft.draft_status = CommunicationDraftStatus.GRAPH_DRAFT_CREATED
        await create_version(
            self.session,
            draft,
            actor_id=actor.actor_id,
            change_reason="Graph-generated recipients imported",
        )
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="outbound_draft",
            entity_id=draft.id,
            action="graph_reply_draft_created",
            after={"revision": draft.local_revision, "status": draft.draft_status},
            metadata={"immutable_graph_id_retained": True},
        )
        await self.session.commit()
        return draft

    async def push_local(self, draft_id: uuid.UUID, actor: CurrentActor) -> OutboundDraft:
        """Push a portal-created local revision to the existing Graph draft."""
        draft, plan, _, mailbox = await self._context(draft_id)
        if not draft.graph_draft_message_id:
            return draft
        if draft.draft_status in {
            CommunicationDraftStatus.SEND_QUEUED,
            CommunicationDraftStatus.SENDING,
            CommunicationDraftStatus.SEND_ACCEPTED,
            CommunicationDraftStatus.SEND_AMBIGUOUS,
            CommunicationDraftStatus.SENT_COPY_VERIFIED,
        }:
            raise StateConflictError("A queued, sending, or sent draft cannot be synchronized.")
        mailbox_identity = mailbox.graph_user_id or mailbox.address
        current = await self.client.get(mailbox_identity, draft.graph_draft_message_id)
        if current.get("isDraft") is not True:
            await self._mark_no_longer_draft(draft)
            raise StateConflictError("Graph message is no longer a draft; reconciliation queued.")
        current_key = str(current.get("changeKey") or "") or None
        current_etag = str(current.get("@odata.etag") or "") or None
        if current_key != draft.graph_change_key or current_etag != draft.graph_etag:
            await self.sync(draft_id, actor)
            raise StateConflictError("Outlook changed the draft; review the imported revision.")
        changes: dict[str, Any] = {
            "subject": draft.subject,
            "body": {
                "contentType": "HTML" if draft.body_html else "Text",
                "content": draft.body_html or draft.body_text or "",
            },
            "toRecipients": _graph_recipients(draft.to_recipients),
            "ccRecipients": _graph_recipients(draft.cc_recipients),
        }
        if plan.bcc_authorized:
            changes["bccRecipients"] = _graph_recipients(draft.bcc_recipients)
        elif draft.bcc_recipients:
            raise StateConflictError("BCC recipients are not authorized by the response plan.")
        await self.client.patch(
            mailbox_identity,
            draft.graph_draft_message_id,
            changes,
            etag=draft.graph_etag,
        )
        final = await self.client.get(mailbox_identity, draft.graph_draft_message_id)
        if final.get("isDraft") is not True:
            await self._mark_no_longer_draft(draft)
            raise StateConflictError("Graph message is no longer a draft; reconciliation queued.")
        final_text, final_html = _body(final)
        final_recipients = (
            _recipients(final.get("toRecipients")),
            _recipients(final.get("ccRecipients")),
            _recipients(final.get("bccRecipients")),
        )
        expected_body = sha256_text(
            f"{draft.subject}\n{draft.body_text or ''}\n{draft.body_html or ''}"
        )
        actual_body = sha256_text(
            f"{final.get('subject') or ''}\n{final_text or ''}\n{final_html or ''}"
        )
        if (
            expected_body != actual_body
            or recipient_set_hash(*final_recipients) != draft.recipient_set_sha256
        ):
            await self.sync(draft_id, actor)
            raise StateConflictError("Graph normalized the draft differently; review is required.")
        draft.graph_change_key = str(final.get("changeKey") or "") or None
        draft.graph_etag = str(final.get("@odata.etag") or "") or None
        draft.graph_last_synced_at = utcnow()
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="outbound_draft",
            entity_id=draft.id,
            action="portal_revision_synchronized_to_graph",
            after={"revision": draft.local_revision, "status": draft.draft_status},
        )
        await self.session.commit()
        return draft

    async def reconcile(
        self, draft_id: uuid.UUID, actor: CurrentActor
    ) -> tuple[OutboundDraft, bool]:
        """Reconcile either a known draft or an ambiguous createReply outcome."""
        draft, plan, email, mailbox = await self._context(draft_id)
        if draft.graph_draft_message_id:
            if draft.draft_status == CommunicationDraftStatus.GRAPH_DRAFT_PENDING:
                return await self._finalize(draft, plan, mailbox, actor), False
            return await self.sync(draft_id, actor)
        if draft.draft_status != CommunicationDraftStatus.GRAPH_DRAFT_PENDING:
            raise StateConflictError("There is no ambiguous Graph draft creation to reconcile.")
        if not email.conversation_id:
            draft.draft_status = CommunicationDraftStatus.SEND_FAILED_REVIEW
            await self.session.commit()
            raise StateConflictError(
                "Source conversation identity is missing; manual Graph draft review is required."
            )
        candidates = await self.client.reply_candidates(
            mailbox.graph_user_id or mailbox.address, email.conversation_id
        )
        intent_window = draft.updated_at - timedelta(minutes=2)
        recent_candidates = []
        for candidate in candidates:
            created_at = self._candidate_created_at(candidate)
            if created_at is not None and created_at >= intent_window:
                recent_candidates.append(candidate)
        candidates = recent_candidates
        if len(candidates) != 1:
            raise StateConflictError(
                "Graph draft creation remains ambiguous; exactly one candidate was not found."
            )
        draft.graph_draft_message_id = str(candidates[0]["id"])
        await self.session.commit()
        return await self._finalize(draft, plan, mailbox, actor), False

    @staticmethod
    def _candidate_created_at(candidate: dict[str, Any]) -> datetime | None:
        value = candidate.get("createdDateTime")
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    async def _mark_no_longer_draft(self, draft: OutboundDraft) -> None:
        draft.draft_status = CommunicationDraftStatus.SEND_AMBIGUOUS
        await CommunicationJobRepository(self.session).enqueue(
            job_type=CommunicationJobType.RECONCILE_SEND,
            idempotency_key=f"graph-draft-no-longer-draft:{draft.id}:{draft.local_revision}",
            draft_id=draft.id,
            email_id=draft.email_id,
            task_id=draft.task_id,
            priority=1,
            max_attempts=self.settings.communication_send_reconciliation_max_attempts,
            delay_seconds=self.settings.communication_send_reconciliation_initial_delay_seconds,
        )
        await self.session.commit()

    async def sync(
        self,
        draft_id: uuid.UUID,
        actor: CurrentActor,
        *,
        allow_expected_transport_metadata_change: bool = False,
    ) -> tuple[OutboundDraft, bool]:
        draft, _, _, mailbox = await self._context(draft_id)
        if not draft.graph_draft_message_id:
            raise StateConflictError("Graph draft is missing.")
        try:
            graph = await self.client.get(
                mailbox.graph_user_id or mailbox.address, draft.graph_draft_message_id
            )
        except GraphApiError as exc:
            if exc.status_code == 404:
                await invalidate_approval(self.session, draft, "Graph draft is missing")
                draft.draft_status = CommunicationDraftStatus.SEND_FAILED_REVIEW
                await self.session.commit()
                raise StateConflictError(
                    "Graph draft is missing; explicit operator review is required."
                ) from None
            raise
        if graph.get("isDraft") is not True:
            await self._mark_no_longer_draft(draft)
            return draft, True
        body_text, body_html = _body(graph)
        to_recipients = _recipients(graph.get("toRecipients"))
        cc_recipients = _recipients(graph.get("ccRecipients"))
        bcc_recipients = _recipients(graph.get("bccRecipients"))
        attachments_match = await graph_attachments_match(
            self.session,
            self.client,
            mailbox.graph_user_id or mailbox.address,
            draft,
            graph_has_attachments=graph.get("hasAttachments") is True,
        )
        material_changed = any(
            (
                str(graph.get("subject") or "") != draft.subject,
                sha256_text(f"{graph.get('subject') or ''}\n{body_text or ''}\n{body_html or ''}")
                != draft.body_sha256,
                recipient_set_hash(to_recipients, cc_recipients, bcc_recipients)
                != draft.recipient_set_sha256,
                not attachments_match,
            )
        )
        next_change_key = str(graph.get("changeKey") or "") or None
        next_etag = str(graph.get("@odata.etag") or "") or None
        identity_changed = (
            next_change_key != draft.graph_change_key or next_etag != draft.graph_etag
        )
        changed = material_changed or (
            identity_changed and not allow_expected_transport_metadata_change
        )
        draft.graph_change_key = next_change_key
        draft.graph_etag = next_etag
        draft.graph_last_synced_at = utcnow()
        if changed:
            draft.subject = str(graph.get("subject") or "")
            draft.body_text, draft.body_html = body_text, body_html
            draft.to_recipients, draft.cc_recipients = to_recipients, cc_recipients
            draft.bcc_recipients = bcc_recipients
            await invalidate_approval(self.session, draft, "external Outlook draft edit")
            await create_version(
                self.session,
                draft,
                actor_id=actor.actor_id,
                change_reason="EXTERNAL_DRAFT_EDIT",
            )
            draft.draft_status = CommunicationDraftStatus.CHANGES_REQUESTED
            add_communication_audit(
                self.session,
                actor=actor,
                entity_type="outbound_draft",
                entity_id=draft.id,
                action="external_graph_draft_edit_detected",
                after={"revision": draft.local_revision, "status": draft.draft_status},
            )
        await self.session.commit()
        return draft, changed

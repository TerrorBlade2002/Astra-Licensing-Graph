"""Draft snapshot creation and approval invalidation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.communications.enums import ApprovalDecision
from app.communications.hashes import (
    attachment_set_hash,
    canonical_sha256,
    recipient_set_hash,
    sha256_text,
)
from app.core.metrics import (
    COMMUNICATION_DRAFT_REVISIONS_TOTAL,
    COMMUNICATION_SEND_APPROVALS_INVALIDATED_TOTAL,
)
from app.models import OutboundDraft, OutboundDraftAttachment, OutboundDraftVersion, SendApproval
from app.models.mixins import utcnow


async def attachment_manifest(session: AsyncSession, draft_id: Any) -> list[dict[str, Any]]:
    rows = list(
        await session.scalars(
            select(OutboundDraftAttachment).where(
                OutboundDraftAttachment.outbound_draft_id == draft_id,
                OutboundDraftAttachment.removed_at.is_(None),
            )
        )
    )
    return [
        {
            "id": str(row.id),
            "document_id": str(row.document_id) if row.document_id else None,
            "document_version_id": str(row.document_version_id)
            if row.document_version_id
            else None,
            "filename": row.filename,
            "size_bytes": row.size_bytes,
            "content_sha256": row.content_sha256,
            "graph_attachment_id": row.graph_attachment_id,
            "status": row.status,
        }
        for row in rows
    ]


async def create_version(
    session: AsyncSession,
    draft: OutboundDraft,
    *,
    actor_id: str,
    change_reason: str | None,
    increment: bool = True,
) -> OutboundDraftVersion:
    manifest = await attachment_manifest(session, draft.id)
    if increment:
        draft.local_revision += 1
    draft.body_sha256 = sha256_text(
        f"{draft.subject}\n{draft.body_text or ''}\n{draft.body_html or ''}"
    )
    draft.recipient_set_sha256 = recipient_set_hash(
        draft.to_recipients, draft.cc_recipients, draft.bcc_recipients
    )
    draft.attachment_set_sha256 = attachment_set_hash(manifest)
    snapshot = canonical_sha256(
        {
            "subject": draft.subject,
            "body": draft.body_sha256,
            "recipients": draft.recipient_set_sha256,
            "attachments": draft.attachment_set_sha256,
            "revision": draft.local_revision,
        }
    )
    version = OutboundDraftVersion(
        outbound_draft_id=draft.id,
        revision=draft.local_revision,
        subject=draft.subject,
        body_text=draft.body_text,
        body_html=draft.body_html,
        to_recipients=draft.to_recipients,
        cc_recipients=draft.cc_recipients,
        bcc_recipients=draft.bcc_recipients,
        attachment_manifest=manifest,
        body_sha256=draft.body_sha256,
        recipient_set_sha256=draft.recipient_set_sha256,
        attachment_set_sha256=draft.attachment_set_sha256,
        snapshot_sha256=snapshot,
        change_reason=change_reason,
        created_by_actor=actor_id,
    )
    session.add(version)
    await session.flush()
    COMMUNICATION_DRAFT_REVISIONS_TOTAL.inc()
    draft.current_version_id = version.id
    draft.last_edited_by_actor = actor_id
    return version


async def invalidate_approval(session: AsyncSession, draft: OutboundDraft, reason: str) -> None:
    approvals = list(
        await session.scalars(
            select(SendApproval).where(
                SendApproval.outbound_draft_id == draft.id,
                SendApproval.decision.in_(
                    [
                        ApprovalDecision.APPROVED,
                        ApprovalDecision.PENDING_SECOND_APPROVAL,
                    ]
                ),
                SendApproval.invalidated_at.is_(None),
            )
        )
    )
    now = utcnow()
    for approval in approvals:
        approval.decision = ApprovalDecision.INVALIDATED
        approval.invalidated_at = now
        approval.invalidation_reason = reason
        COMMUNICATION_SEND_APPROVALS_INVALIDATED_TOTAL.inc()
    draft.approval_snapshot_sha256 = None
    draft.approved_at = None

"""Transmission-time policy for governed outbound attachments."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentVersion, OutboundDraftAttachment


def transmission_blockers(
    document: Document,
    version: DocumentVersion,
    *,
    today: date | None = None,
) -> list[str]:
    """Return stable blockers that must be rechecked before upload and send."""

    current_date = today or date.today()
    blockers: list[str] = []
    if document.lifecycle_status != "ACTIVE":
        blockers.append("DOCUMENT_NOT_ACTIVE")
    if document.approval_status != "APPROVED" or not document.approved_for_reuse:
        blockers.append("DOCUMENT_NOT_APPROVED")
    if version.storage_status != "AVAILABLE":
        blockers.append("DOCUMENT_QUARANTINED")
    if document.expiry_date and document.expiry_date < current_date:
        blockers.append("DOCUMENT_EXPIRED")
    if document.current_version_id != version.id:
        blockers.append("DOCUMENT_SUPERSEDED")
    if (
        version.document_id != document.id
        or version.content_sha256 != document.content_sha256
        or version.size_bytes != document.size_bytes
    ):
        blockers.append("DOCUMENT_HASH_INVALID")
    if document.confidentiality_level == "RESTRICTED":
        blockers.append("DOCUMENT_TRANSMISSION_BLOCKED")
    return list(dict.fromkeys(blockers))


async def validate_draft_attachments(
    session: AsyncSession,
    draft_id: object,
    *,
    require_graph_uploaded: bool,
) -> tuple[list[OutboundDraftAttachment], list[str]]:
    """Revalidate the exact active set instead of trusting selection-time state."""

    rows = list(
        await session.scalars(
            select(OutboundDraftAttachment).where(
                OutboundDraftAttachment.outbound_draft_id == draft_id,
                OutboundDraftAttachment.removed_at.is_(None),
            )
        )
    )
    blockers: list[str] = []
    for row in rows:
        if not row.document_id or not row.document_version_id:
            blockers.append("UNCONTROLLED_ATTACHMENT")
            continue
        document = await session.get(Document, row.document_id)
        version = await session.get(DocumentVersion, row.document_version_id)
        if document is None or version is None:
            blockers.append("DOCUMENT_NOT_FOUND")
            continue
        blockers.extend(transmission_blockers(document, version))
        if (
            row.content_sha256 != version.content_sha256
            or row.size_bytes != version.size_bytes
            or row.filename != version.filename
        ):
            blockers.append("DOCUMENT_HASH_INVALID")
        if require_graph_uploaded and (
            row.status != "GRAPH_UPLOADED" or not row.graph_attachment_id
        ):
            blockers.append("GRAPH_ATTACHMENT_MISSING")
    return rows, list(dict.fromkeys(blockers))

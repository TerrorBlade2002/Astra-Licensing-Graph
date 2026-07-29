"""Document lifecycle, optimistic metadata updates, and reuse approval."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidStateTransitionError, NotFoundError, StateConflictError
from app.documents.enums import ApprovalStatus, LifecycleStatus
from app.documents.policies import can_approve_for_reuse
from app.models import Document
from app.models.mixins import utcnow
from app.repositories.documents import DocumentRepository


class DocumentCatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DocumentRepository(session)

    async def require(self, document_id: uuid.UUID, *, lock: bool = False) -> Document:
        document = await self.repo.get(document_id, lock=lock)
        if document is None:
            raise NotFoundError("Document not found.")
        return document

    async def update_metadata(
        self,
        document_id: uuid.UUID,
        changes: dict[str, Any],
        *,
        expected_updated_at: datetime,
        actor_id: str,
    ) -> Document:
        document = await self.require(document_id, lock=True)
        if document.updated_at != expected_updated_at:
            raise StateConflictError("Document metadata changed since it was retrieved.")
        allowed = {
            "canonical_title",
            "document_type",
            "confidentiality_level",
            "legal_entity",
            "jurisdiction",
            "license_type",
            "license_number",
            "vendor",
            "issue_date",
            "effective_date",
            "expiry_date",
            "renewal_due_date",
            "reusable",
        }
        before = {key: getattr(document, key) for key in changes if key in allowed}
        for key, value in changes.items():
            if key in allowed:
                setattr(document, key, value)
        document.updated_at = utcnow()
        self.repo.add_event(
            document.id,
            "METADATA_UPDATED",
            actor_type="HUMAN",
            actor_id=actor_id,
            before=_jsonable(before),
            after=_jsonable({key: getattr(document, key) for key in before}),
        )
        await self.session.commit()
        return document

    async def submit_for_review(self, document_id: uuid.UUID, actor_id: str) -> Document:
        document = await self.require(document_id, lock=True)
        if document.approval_status not in (ApprovalStatus.UNREVIEWED, ApprovalStatus.REJECTED):
            raise InvalidStateTransitionError(
                "Document cannot be submitted from its current state."
            )
        return await self._approval(
            document, ApprovalStatus.PENDING_REVIEW, actor_id, "SUBMITTED_FOR_REVIEW"
        )

    async def approve(self, document_id: uuid.UUID, actor_id: str) -> Document:
        document = await self.require(document_id, lock=True)
        if document.approval_status not in (
            ApprovalStatus.PENDING_REVIEW,
            ApprovalStatus.UNREVIEWED,
        ):
            raise InvalidStateTransitionError("Document cannot be approved from its current state.")
        document.approved_at = utcnow()
        document.approved_by_actor = actor_id
        return await self._approval(document, ApprovalStatus.APPROVED, actor_id, "APPROVED")

    async def reject(self, document_id: uuid.UUID, actor_id: str) -> Document:
        document = await self.require(document_id, lock=True)
        document.approved_for_reuse = False
        return await self._approval(document, ApprovalStatus.REJECTED, actor_id, "REJECTED")

    async def _approval(
        self, document: Document, status: ApprovalStatus, actor_id: str, event: str
    ) -> Document:
        before = {"approval_status": document.approval_status}
        document.approval_status = status.value
        self.repo.add_event(
            document.id,
            event,
            actor_type="HUMAN",
            actor_id=actor_id,
            before=before,
            after={"approval_status": status.value},
        )
        await self.session.commit()
        return document

    async def approve_reuse(self, document_id: uuid.UUID, actor_id: str) -> Document:
        document = await self.require(document_id, lock=True)
        version = (
            await self.repo.version(document.id, document.current_version_id)
            if document.current_version_id
            else None
        )
        allowed, reason = can_approve_for_reuse(
            lifecycle_status=document.lifecycle_status,
            approval_status=document.approval_status,
            storage_status=version.storage_status if version else "MISSING",
            confidentiality_level=document.confidentiality_level,
            expiry_date=document.expiry_date,
            hash_verified=bool(version and version.content_sha256 == document.content_sha256),
            required_metadata_complete=bool(document.document_type and document.canonical_title),
        )
        if not allowed:
            raise InvalidStateTransitionError(f"Document cannot be approved for reuse: {reason}.")
        document.reusable = True
        document.approved_for_reuse = True
        self.repo.add_event(document.id, "REUSE_APPROVED", actor_type="HUMAN", actor_id=actor_id)
        await self.session.commit()
        return document

    async def revoke_reuse(self, document_id: uuid.UUID, actor_id: str) -> Document:
        document = await self.require(document_id, lock=True)
        document.approved_for_reuse = False
        self.repo.add_event(document.id, "REUSE_REVOKED", actor_type="HUMAN", actor_id=actor_id)
        await self.session.commit()
        return document

    async def supersede(self, document_id: uuid.UUID, actor_id: str) -> Document:
        document = await self.require(document_id, lock=True)
        document.lifecycle_status = LifecycleStatus.SUPERSEDED.value
        document.superseded_at = utcnow()
        document.approved_for_reuse = False
        self.repo.add_event(document.id, "SUPERSEDED", actor_type="HUMAN", actor_id=actor_id)
        await self.session.commit()
        return document

    async def mark_expired(self, today: date | None = None) -> int:
        from sqlalchemy import select

        today = today or date.today()
        documents = list(
            (
                await self.session.scalars(
                    select(Document).where(
                        Document.lifecycle_status == LifecycleStatus.ACTIVE.value,
                        Document.expiry_date.is_not(None),
                        Document.expiry_date < today,
                    )
                )
            ).all()
        )
        for document in documents:
            document.lifecycle_status = LifecycleStatus.EXPIRED.value
            document.approved_for_reuse = False
            self.repo.add_event(document.id, "EXPIRED", actor_type="SYSTEM", actor_id=None)
        await self.session.commit()
        return len(documents)


def _jsonable(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in values.items()
    }

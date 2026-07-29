"""Database access for governed documents and their append-only history."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentLink, DocumentMetadataEvent, DocumentVersion
from app.models.mixins import utcnow


@dataclass(frozen=True)
class DocumentSearch:
    document_type: str | None = None
    lifecycle_status: str | None = None
    approval_status: str | None = None
    confidentiality_level: str | None = None
    legal_entity: str | None = None
    jurisdiction: str | None = None
    license_type: str | None = None
    license_number: str | None = None
    vendor: str | None = None
    reusable: bool | None = None
    approved_for_reuse: bool | None = None
    expires_before: date | None = None
    expires_after: date | None = None
    source_type: str | None = None
    source_email_id: uuid.UUID | None = None
    source_task_id: uuid.UUID | None = None
    filename_contains: str | None = None


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, document_id: uuid.UUID, *, lock: bool = False) -> Document | None:
        stmt = select(Document).where(Document.id == document_id)
        if lock:
            stmt = stmt.with_for_update()
        return cast(Document | None, await self.session.scalar(stmt))

    async def find_exact_hash(self, sha256: str) -> Document | None:
        return cast(
            Document | None,
            await self.session.scalar(
                select(Document)
                .where(Document.content_sha256 == sha256)
                .order_by(Document.created_at.asc())
                .limit(1)
            ),
        )

    @staticmethod
    def _filtered(stmt: Select[Any], filters: DocumentSearch) -> Select[Any]:
        for field in (
            "document_type",
            "lifecycle_status",
            "approval_status",
            "confidentiality_level",
            "legal_entity",
            "jurisdiction",
            "license_type",
            "license_number",
            "vendor",
            "reusable",
            "approved_for_reuse",
            "source_type",
            "source_email_id",
            "source_task_id",
        ):
            value = getattr(filters, field)
            if value is not None:
                stmt = stmt.where(getattr(Document, field) == value)
        if filters.expires_before:
            stmt = stmt.where(Document.expiry_date <= filters.expires_before)
        if filters.expires_after:
            stmt = stmt.where(Document.expiry_date >= filters.expires_after)
        if filters.filename_contains:
            escaped = filters.filename_contains.replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(Document.current_filename.ilike(f"%{escaped}%", escape="\\"))
        return stmt

    async def search(
        self, filters: DocumentSearch, *, page: int, page_size: int, include_restricted: bool
    ) -> tuple[list[Document], int]:
        base = select(Document)
        count = select(func.count(Document.id))
        if not include_restricted:
            base = base.where(Document.confidentiality_level != "RESTRICTED")
            count = count.where(Document.confidentiality_level != "RESTRICTED")
        base = self._filtered(base, filters)
        count = self._filtered(count, filters)
        total = int(await self.session.scalar(count) or 0)
        rows = list(
            (
                await self.session.scalars(
                    base.order_by(Document.updated_at.desc(), Document.id.asc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return rows, total

    async def versions(self, document_id: uuid.UUID) -> list[DocumentVersion]:
        return list(
            (
                await self.session.scalars(
                    select(DocumentVersion)
                    .where(DocumentVersion.document_id == document_id)
                    .order_by(DocumentVersion.version_number.desc())
                )
            ).all()
        )

    async def version(
        self, document_id: uuid.UUID, version_id: uuid.UUID
    ) -> DocumentVersion | None:
        return cast(
            DocumentVersion | None,
            await self.session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.id == version_id,
                )
            ),
        )

    async def next_version_number(self, document_id: uuid.UUID) -> int:
        current = await self.session.scalar(
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == document_id)
            .with_for_update()
        )
        return int(current or 0) + 1

    async def links(self, document_id: uuid.UUID) -> list[DocumentLink]:
        return list(
            (
                await self.session.scalars(
                    select(DocumentLink)
                    .where(DocumentLink.document_id == document_id)
                    .order_by(DocumentLink.created_at.asc())
                )
            ).all()
        )

    async def events(
        self, document_id: uuid.UUID, *, limit: int = 50
    ) -> list[DocumentMetadataEvent]:
        return list(
            (
                await self.session.scalars(
                    select(DocumentMetadataEvent)
                    .where(DocumentMetadataEvent.document_id == document_id)
                    .order_by(DocumentMetadataEvent.occurred_at.desc())
                    .limit(limit)
                )
            ).all()
        )

    def add_event(
        self,
        document_id: uuid.UUID,
        event_type: str,
        *,
        actor_type: str,
        actor_id: str | None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        note: str | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> DocumentMetadataEvent:
        event = DocumentMetadataEvent(
            id=uuid.uuid4(),
            document_id=document_id,
            event_type=event_type,
            before_data=before,
            after_data=after,
            actor_type=actor_type,
            actor_id=actor_id,
            correlation_id=correlation_id,
            note=note,
            occurred_at=utcnow(),
        )
        self.session.add(event)
        return event

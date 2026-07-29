"""Non-destructive catalog/SharePoint integrity verification."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.repositories.documents import DocumentRepository
from app.sharepoint.client import SharePointClient


class DocumentIntegrityService:
    def __init__(self, session: AsyncSession, client: SharePointClient) -> None:
        self.session = session
        self.client = client
        self.repo = DocumentRepository(session)

    async def verify(self, document_id: uuid.UUID) -> dict[str, Any]:
        document = await self.session.get(Document, document_id)
        if not document or not document.current_version_id:
            return {"ok": False, "checks": {"catalog": False}}
        version = await self.repo.version(document.id, document.current_version_id)
        if not version:
            return {"ok": False, "checks": {"current_version": False}}
        item = await self.client.get_drive_item(version.graph_drive_id, version.graph_drive_item_id)
        checks = {
            "drive_item_exists": True,
            "size_matches": item.size == version.size_bytes,
            "current_version_pointer": version.id == document.current_version_id,
            "etag_matches": not version.graph_etag or version.graph_etag == item.etag,
        }
        if not all(checks.values()):
            document.approved_for_reuse = False
            self.repo.add_event(
                document.id,
                "INTEGRITY_MISMATCH",
                actor_type="SYSTEM",
                actor_id="document-integrity",
                after=checks,
            )
            await self.session.commit()
        return {"ok": all(checks.values()), "checks": checks}

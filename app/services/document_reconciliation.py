"""Checkpoint-safe SharePoint drive delta reconciliation."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.enums import (
    ApprovalStatus,
    ConfidentialityLevel,
    LifecycleStatus,
    SourceType,
    StorageStatus,
)
from app.graph.errors import GraphApiError
from app.models import (
    Document,
    DocumentVersion,
    SharePointDrive,
    SharePointSite,
    SharePointSyncState,
)
from app.models.mixins import utcnow
from app.repositories.documents import DocumentRepository
from app.sharepoint.client import SharePointClient
from app.sharepoint.urls import opaque_url_fingerprint


class DocumentReconciliationService:
    def __init__(self, session: AsyncSession, client: SharePointClient) -> None:
        self.session = session
        self.client = client
        self.repo = DocumentRepository(session)

    async def reconcile(self, drive_id: uuid.UUID) -> dict[str, int]:
        drive = await self.session.get(SharePointDrive, drive_id)
        if drive is None:
            raise ValueError("SharePoint drive is not cataloged.")
        state = await self.session.scalar(
            select(SharePointSyncState).where(SharePointSyncState.drive_id == drive.id)
        )
        if state is None:
            state = SharePointSyncState(id=uuid.uuid4(), drive_id=drive.id)
            self.session.add(state)
        state.last_started_at = utcnow()
        checkpoint = None if state.needs_rebaseline else state.delta_link
        pages: list[list[dict[str, Any]]] = []
        next_url = checkpoint
        final_delta: str | None = None
        try:
            while True:
                payload = await self.client.drive_delta(drive.graph_drive_id, next_url)
                pages.append(list(payload.get("value", [])))
                next_url = payload.get("@odata.nextLink")
                if next_url:
                    continue
                final_delta = payload.get("@odata.deltaLink")
                if not final_delta:
                    raise ValueError("SharePoint delta response did not provide a checkpoint.")
                break
        except GraphApiError as exc:
            if exc.status_code in (400, 410):
                state.needs_rebaseline = True
                state.last_error_code = "invalid_delta_token"
                state.last_error_message = "Stored SharePoint delta token is no longer valid."
                await self.session.commit()
            raise
        changes = 0
        for page in pages:
            for item in page:
                if "folder" in item:
                    continue
                await self._apply_item(drive, item)
                changes += 1
        state.delta_link = final_delta
        state.needs_rebaseline = False
        state.last_completed_at = utcnow()
        state.last_delta_url_fingerprint = opaque_url_fingerprint(final_delta)
        state.last_page_count = len(pages)
        state.last_change_count = changes
        state.last_error_code = None
        state.last_error_message = None
        await self.session.commit()
        return {"pages": len(pages), "changes": changes}

    async def _apply_item(self, drive: SharePointDrive, item: dict[str, Any]) -> None:
        item_id = str(item.get("id") or "")
        if not item_id:
            return
        version = await self.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.graph_drive_id == drive.graph_drive_id,
                DocumentVersion.graph_drive_item_id == item_id,
            )
        )
        if version is None:
            if "deleted" not in item:
                await self._import_unknown(drive, item)
            return
        document = await self.session.get(Document, version.document_id)
        if document is None:
            return
        if "deleted" in item:
            document.lifecycle_status = LifecycleStatus.DELETED_EXTERNALLY.value
            document.approved_for_reuse = False
            version.storage_status = StorageStatus.DELETED_EXTERNALLY.value
            self.repo.add_event(
                document.id, "DELETED_EXTERNALLY", actor_type="SYSTEM", actor_id=None
            )
            return
        new_name = str(item.get("name") or version.filename)
        if new_name != version.filename:
            before = {"filename": version.filename}
            version.filename = new_name
            document.current_filename = new_name
            self.repo.add_event(
                document.id,
                "RENAMED_EXTERNALLY",
                actor_type="SYSTEM",
                actor_id=None,
                before=before,
                after={"filename": new_name},
            )
        parent_id = (item.get("parentReference") or {}).get("id")
        if parent_id and parent_id != version.parent_graph_drive_item_id:
            before_move: dict[str, Any] = {
                "parent_graph_drive_item_id": version.parent_graph_drive_item_id
            }
            version.parent_graph_drive_item_id = str(parent_id)
            self.repo.add_event(
                document.id,
                "MOVED_EXTERNALLY",
                actor_type="SYSTEM",
                actor_id=None,
                before=before_move,
                after={"parent_graph_drive_item_id": str(parent_id)},
            )
        version.web_url = item.get("webUrl") or version.web_url
        version.graph_etag = item.get("eTag") or version.graph_etag
        version.graph_ctag = item.get("cTag") or version.graph_ctag

    async def _import_unknown(self, drive: SharePointDrive, item: dict[str, Any]) -> None:
        site = await self.session.get(SharePointSite, drive.site_id)
        if site is None:
            return
        item_id = str(item["id"])
        fields = (item.get("listItem") or {}).get("fields") or {}
        key = str(fields.get("AstraDocumentKey") or f"SP-{uuid.uuid4().hex.upper()}")
        placeholder_hash = hashlib.sha256(
            f"unverified:{drive.graph_drive_id}:{item_id}".encode()
        ).hexdigest()
        document = Document(
            id=uuid.uuid4(),
            document_key=key,
            canonical_title=str(item.get("name") or "Unreviewed SharePoint document"),
            current_filename=str(item.get("name") or "unknown"),
            document_type="OTHER",
            lifecycle_status=LifecycleStatus.ACTIVE.value,
            approval_status=ApprovalStatus.UNREVIEWED.value,
            confidentiality_level=ConfidentialityLevel.INTERNAL.value,
            reusable=False,
            approved_for_reuse=False,
            content_sha256=placeholder_hash,
            mime_type=((item.get("file") or {}).get("mimeType")),
            size_bytes=int(item.get("size") or 0),
            source_type=SourceType.SHAREPOINT_EXISTING.value,
            created_by_actor="sharepoint-reconciliation",
        )
        version = DocumentVersion(
            id=uuid.uuid4(),
            document_id=document.id,
            version_number=1,
            graph_site_id=site.graph_site_id,
            graph_drive_id=drive.graph_drive_id,
            graph_drive_item_id=item_id,
            graph_list_id=drive.graph_list_id,
            graph_list_item_id=str((item.get("listItem") or {}).get("id") or "") or None,
            parent_graph_drive_item_id=(item.get("parentReference") or {}).get("id"),
            filename=document.current_filename,
            web_url=item.get("webUrl"),
            mime_type=document.mime_type,
            size_bytes=document.size_bytes,
            content_sha256=placeholder_hash,
            graph_etag=item.get("eTag"),
            graph_ctag=item.get("cTag"),
            storage_status=StorageStatus.AVAILABLE.value,
            uploaded_by_actor="sharepoint-existing",
            uploaded_at=utcnow(),
            discovered_at=utcnow(),
        )
        self.session.add(document)
        await self.session.flush()
        self.session.add(version)
        await self.session.flush()
        document.current_version_id = version.id
        self.repo.add_event(document.id, "IMPORTED_EXISTING", actor_type="SYSTEM", actor_id=None)

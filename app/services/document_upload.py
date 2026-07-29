"""Explicit intent/upload/finalize workflow for governed documents."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.enums import (
    ApprovalStatus,
    ConfidentialityLevel,
    LifecycleStatus,
    SourceType,
    StorageStatus,
)
from app.documents.metadata import REQUIRED_COLUMNS, discover_column_mapping, to_sharepoint_fields
from app.documents.naming import canonical_filename
from app.documents.policies import validate_content
from app.documents.routing import route_document
from app.evidence.sharepoint import SharePointEvidenceStore
from app.models import (
    Document,
    DocumentLink,
    DocumentVersion,
    SharePointDrive,
    SharePointSite,
)
from app.models.mixins import utcnow
from app.repositories.documents import DocumentRepository


@dataclass(frozen=True)
class DocumentUploadMetadata:
    canonical_title: str
    document_type: str
    legal_entity: str | None = None
    jurisdiction: str | None = None
    license_type: str | None = None
    license_number: str | None = None
    vendor: str | None = None
    issue_date: date | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    renewal_due_date: date | None = None
    confidentiality_level: str = ConfidentialityLevel.INTERNAL.value
    reusable: bool = False


@dataclass(frozen=True)
class UploadOutcome:
    document: Document
    version: DocumentVersion | None
    duplicate: bool


class DocumentUploadService:
    def __init__(
        self,
        session: AsyncSession,
        store: SharePointEvidenceStore,
        *,
        allowed_mime_types: list[str],
        allowed_extensions: list[str],
        max_bytes: int,
        filename_max_length: int,
    ) -> None:
        self.session = session
        self.store = store
        self.allowed_mime_types = allowed_mime_types
        self.allowed_extensions = allowed_extensions
        self.max_bytes = max_bytes
        self.filename_max_length = filename_max_length
        self.repo = DocumentRepository(session)

    async def upload_path(
        self,
        source: Path,
        *,
        original_filename: str,
        mime_type: str,
        metadata: DocumentUploadMetadata,
        source_type: SourceType,
        actor_id: str,
        idempotency_key: str,
        links: list[tuple[str, uuid.UUID | None, str | None, str]] | None = None,
        source_storage_uri: str | None = None,
    ) -> UploadOutcome:
        size = source.stat().st_size
        validate_content(
            filename=original_filename,
            mime_type=mime_type,
            size_bytes=size,
            max_bytes=self.max_bytes,
            allowed_mime_types=self.allowed_mime_types,
            allowed_extensions=self.allowed_extensions,
        )
        sha256 = await _hash_file(source)
        duplicate = await self.repo.find_exact_hash(sha256)
        if duplicate is not None:
            self._add_links(duplicate.id, links or [], actor_id)
            self.repo.add_event(
                duplicate.id,
                "LINKED_DUPLICATE_SOURCE",
                actor_type="HUMAN",
                actor_id=actor_id,
                note="Exact binary duplicate; no second upload performed.",
            )
            await self.session.commit()
            return UploadOutcome(duplicate, None, True)

        purpose = route_document(metadata.document_type)
        drive = await self.session.scalar(
            select(SharePointDrive).where(
                SharePointDrive.purpose == purpose.value, SharePointDrive.is_active.is_(True)
            )
        )
        if drive is None or not drive.root_drive_item_id:
            raise ValueError(f"No active SharePoint route is configured for {purpose.value}.")
        site = await self.session.get(SharePointSite, drive.site_id)
        if site is None:
            raise ValueError("SharePoint site catalog entry is missing.")

        document_id = uuid.uuid4()
        document_key = f"ASTRA-{document_id.hex.upper()}"
        filename = canonical_filename(
            legal_entity=metadata.legal_entity,
            jurisdiction=metadata.jurisdiction,
            document_type=metadata.document_type,
            relevant_date=metadata.effective_date or metadata.issue_date,
            short_id=document_id.hex[:6],
            original_filename=original_filename,
            allowed_extensions=self.allowed_extensions,
            max_length=self.filename_max_length,
        )
        document = Document(
            id=document_id,
            document_key=document_key,
            canonical_title=metadata.canonical_title,
            original_filename=original_filename,
            current_filename=filename,
            document_type=metadata.document_type,
            lifecycle_status=LifecycleStatus.ACTIVE.value,
            approval_status=ApprovalStatus.UNREVIEWED.value,
            confidentiality_level=metadata.confidentiality_level,
            legal_entity=metadata.legal_entity,
            jurisdiction=metadata.jurisdiction,
            license_type=metadata.license_type,
            license_number=metadata.license_number,
            vendor=metadata.vendor,
            issue_date=metadata.issue_date,
            effective_date=metadata.effective_date,
            expiry_date=metadata.expiry_date,
            renewal_due_date=metadata.renewal_due_date,
            reusable=metadata.reusable,
            approved_for_reuse=False,
            content_sha256=sha256,
            mime_type=mime_type,
            size_bytes=size,
            source_type=source_type.value,
            created_by_actor=actor_id,
        )
        for link_type, entity_id, _external_key, _relationship in links or []:
            if link_type == "EMAIL":
                document.source_email_id = entity_id
            elif link_type == "EMAIL_ATTACHMENT":
                document.source_attachment_id = entity_id
            elif link_type == "TASK":
                document.source_task_id = entity_id
        version = DocumentVersion(
            id=uuid.uuid4(),
            document_id=document.id,
            version_number=1,
            graph_site_id=site.graph_site_id,
            graph_drive_id=drive.graph_drive_id,
            graph_drive_item_id=f"pending:{idempotency_key[:80]}",
            graph_list_id=drive.graph_list_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size,
            content_sha256=sha256,
            storage_status=StorageStatus.UPLOADING.value,
            uploaded_by_actor=actor_id,
            source_storage_uri=source_storage_uri,
            uploaded_at=utcnow(),
        )
        self.session.add_all([document, version])
        self.repo.add_event(document.id, "CREATED", actor_type="HUMAN", actor_id=actor_id)
        await self.session.commit()

        async def file_chunks() -> AsyncIterator[bytes]:
            with source.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    yield chunk

        try:
            result = await self.store.put_stream(
                f"{drive.graph_drive_id}/{drive.root_drive_item_id}/{filename}",
                file_chunks(),
                max_bytes=self.max_bytes,
                content_type=mime_type,
            )
        except Exception:
            version.storage_status = StorageStatus.FAILED.value
            self.repo.add_event(document.id, "UPLOAD_FAILED", actor_type="SYSTEM", actor_id=None)
            await self.session.commit()
            raise

        if result.bytes_written != size or result.sha256_checksum != sha256:
            version.storage_status = StorageStatus.QUARANTINED.value
            document.lifecycle_status = LifecycleStatus.QUARANTINED.value
            self.repo.add_event(document.id, "HASH_MISMATCH", actor_type="SYSTEM", actor_id=None)
            await self.session.commit()
            raise ValueError("SharePoint upload verification failed.")
        version.graph_drive_item_id = result.drive_item_id or version.graph_drive_item_id
        version.graph_list_item_id = result.list_item_id
        version.parent_graph_drive_item_id = drive.root_drive_item_id
        version.web_url = result.web_url
        version.graph_etag = result.etag
        version.graph_ctag = result.ctag
        version.storage_status = StorageStatus.AVAILABLE.value
        document.current_version_id = version.id
        self._add_links(document.id, links or [], actor_id)
        self.repo.add_event(document.id, "UPLOADED", actor_type="SYSTEM", actor_id=None)
        await self.session.commit()
        if drive.graph_list_id and result.list_item_id:
            try:
                columns = await self.store.client.list_columns(
                    site.graph_site_id, drive.graph_list_id
                )
                mapping, incompatible = discover_column_mapping(columns)
                missing = sorted(set(REQUIRED_COLUMNS) - set(mapping))
                if missing or incompatible:
                    raise ValueError("SharePoint custom columns are missing or incompatible.")
                await self.store.client.update_list_item_fields(
                    site.graph_site_id,
                    drive.graph_list_id,
                    result.list_item_id,
                    to_sharepoint_fields(document, mapping),
                )
                self.repo.add_event(
                    document.id, "METADATA_SYNCED", actor_type="SYSTEM", actor_id=None
                )
                await self.session.commit()
            except Exception:
                self.repo.add_event(
                    document.id,
                    "METADATA_SYNC_FAILED",
                    actor_type="SYSTEM",
                    actor_id=None,
                    note="Binary retained; metadata synchronization requires retry.",
                )
                await self.session.commit()
                raise
        return UploadOutcome(document, version, False)

    def _add_links(
        self,
        document_id: uuid.UUID,
        links: list[tuple[str, uuid.UUID | None, str | None, str]],
        actor_id: str,
    ) -> None:
        for link_type, entity_id, external_key, relationship in links:
            self.session.add(
                DocumentLink(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    link_type=link_type,
                    linked_entity_id=entity_id,
                    linked_external_key=external_key,
                    relationship=relationship,
                    created_by_actor=actor_id,
                    link_metadata={},
                )
            )


async def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()

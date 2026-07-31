"""Promotion of immutable email evidence into the governed repository."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.enums import LinkType, SourceType
from app.evidence.filesystem import FilesystemEvidenceStore
from app.evidence.sharepoint import SharePointEvidenceStore
from app.models import EmailAttachment
from app.services.document_upload import (
    DocumentUploadMetadata,
    DocumentUploadService,
    UploadOutcome,
)
from app.sharepoint.urls import parse_sharepoint_storage_uri


class DocumentPromotionService:
    def __init__(self, session: AsyncSession, uploader: DocumentUploadService) -> None:
        self.session = session
        self.uploader = uploader

    async def promote(
        self,
        attachment_id: uuid.UUID,
        *,
        metadata: DocumentUploadMetadata,
        actor_id: str,
        idempotency_key: str,
    ) -> UploadOutcome:
        attachment = await self.session.get(EmailAttachment, attachment_id)
        if attachment is None:
            raise ValueError("Email attachment was not found.")
        if attachment.status != "DOWNLOADED" or not attachment.storage_uri:
            raise ValueError("Email attachment evidence is not available for promotion.")
        cleanup: Path | None = None
        if attachment.storage_uri.startswith("sharepoint://"):
            _site_id, drive_id, item_id = parse_sharepoint_storage_uri(attachment.storage_uri)
            cleanup = Path(tempfile.mkdtemp(prefix="astra-promotion-"))
            local_store = FilesystemEvidenceStore(cleanup)
            # The evidence lives in SharePoint, so promoting it needs a
            # SharePoint-backed store regardless of where the copy will land.
            if not isinstance(self.uploader.store, SharePointEvidenceStore):
                shutil.rmtree(cleanup, ignore_errors=True)
                raise ValueError(
                    "This attachment is stored in SharePoint, which is not enabled here."
                )
            await self.uploader.store.client.download_to_store(
                drive_id,
                item_id,
                local_store,
                "source",
                max_bytes=self.uploader.max_bytes,
            )
            source = cleanup / "source"
        else:
            source = _file_uri_path(attachment.storage_uri)
        if not source.is_file():
            if cleanup:
                shutil.rmtree(cleanup, ignore_errors=True)
            raise ValueError("Email attachment source evidence is missing.")
        if attachment.sha256_checksum and _sha256(source) != attachment.sha256_checksum:
            if cleanup:
                shutil.rmtree(cleanup, ignore_errors=True)
            raise ValueError("Email attachment evidence hash does not match its catalog record.")
        links: list[tuple[str, uuid.UUID | None, str | None, str]] = [
            (LinkType.EMAIL_ATTACHMENT.value, attachment.id, None, "SOURCE"),
            (LinkType.EMAIL.value, attachment.email_id, None, "SOURCE"),
        ]
        try:
            return await self.uploader.upload_path(
                source,
                original_filename=attachment.original_filename or "attachment.bin",
                mime_type=attachment.mime_type or "application/octet-stream",
                metadata=metadata,
                source_type=SourceType.EMAIL_ATTACHMENT,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                links=links,
                source_storage_uri=attachment.storage_uri,
            )
        finally:
            if cleanup:
                shutil.rmtree(cleanup, ignore_errors=True)


def _file_uri_path(uri: str) -> Path:
    parsed = urlsplit(uri)
    if parsed.scheme != "file":
        raise ValueError("Only local filesystem evidence can be promoted by this operation.")
    raw = unquote(parsed.path)
    if parsed.netloc:
        raw = f"//{parsed.netloc}{raw}"
    if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]
    return Path(raw)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()

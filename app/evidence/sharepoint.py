"""SharePoint-backed evidence store with bounded disk spooling."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath

from app.evidence.base import EvidenceMetadata, EvidenceWriteResult
from app.sharepoint.client import SharePointClient
from app.sharepoint.urls import parse_sharepoint_storage_uri, sharepoint_storage_uri


class SharePointEvidenceStore:
    """EvidenceStore-compatible adapter.

    Keys use ``<drive-id>/<parent-item-id>/<filename>``. IDs and the filename
    are validated as path segments; returned storage URIs contain identifiers,
    never temporary download URLs.
    """

    def __init__(
        self,
        client: SharePointClient,
        *,
        site_id: str,
        temp_dir: str | None = None,
        default_drive_id: str | None = None,
        default_parent_id: str = "root",
    ) -> None:
        self.client = client
        self.site_id = site_id
        self.temp_dir = temp_dir
        self.default_drive_id = default_drive_id
        self.default_parent_id = default_parent_id

    def _parts(self, key: str) -> tuple[str, str, str]:
        path = PurePosixPath(key)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("SharePoint evidence key is unsafe")
        if len(path.parts) == 3:
            drive_id, parent_id, filename = path.parts
        elif self.default_drive_id:
            suffix = path.suffix.lower()[:20]
            filename = f"{hashlib.sha256(key.encode()).hexdigest()}{suffix}"
            drive_id, parent_id = self.default_drive_id, self.default_parent_id
        else:
            raise ValueError("SharePoint evidence key must contain drive, parent, and filename")
        if not all((drive_id, parent_id, filename)):
            raise ValueError("SharePoint evidence key contains an empty segment")
        return drive_id, parent_id, filename

    async def put_bytes(
        self, key: str, data: bytes, *, content_type: str = "application/octet-stream"
    ) -> EvidenceWriteResult:
        async def chunks() -> AsyncIterator[bytes]:
            yield data

        return await self.put_stream(
            key, chunks(), max_bytes=max(1, len(data)), content_type=content_type
        )

    async def put_stream(
        self,
        key: str,
        stream: AsyncIterator[bytes],
        *,
        max_bytes: int,
        content_type: str = "application/octet-stream",
    ) -> EvidenceWriteResult:
        drive_id, parent_id, filename = self._parts(key)
        digest = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(dir=self.temp_dir, delete=False) as spool:
            spool_path = Path(spool.name)
            try:
                async for chunk in stream:
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("Streamed content exceeded the configured document limit")
                    digest.update(chunk)
                    spool.write(chunk)
                spool.flush()
            except Exception:
                spool_path.unlink(missing_ok=True)
                raise
        try:
            if size <= self.client.settings.sharepoint_simple_upload_max_bytes:
                result = await self.client.upload_small(
                    drive_id,
                    parent_id,
                    filename,
                    spool_path.read_bytes(),
                    content_type=content_type,
                )
            else:
                session = await self.client.create_upload_session(
                    drive_id,
                    parent_id,
                    filename,
                    conflict_behavior=self.client.settings.sharepoint_upload_conflict_behavior,
                )
                result = await self.client.upload_file_session(
                    session, spool_path, total_bytes=size
                )
        finally:
            spool_path.unlink(missing_ok=True)
        item = result.item
        return EvidenceWriteResult(
            storage_uri=sharepoint_storage_uri(self.site_id, drive_id, item.id),
            bytes_written=size,
            sha256_checksum=digest.hexdigest(),
            content_type=content_type,
            site_id=self.site_id,
            drive_id=drive_id,
            drive_item_id=item.id,
            list_item_id=item.list_item_id,
            web_url=item.web_url,
            etag=item.etag,
            ctag=item.ctag,
            upload_method=result.method,
        )

    async def exists(self, key: str) -> bool:
        drive_id, item_id, _ = self._parts(key)
        try:
            await self.client.get_drive_item(drive_id, item_id)
        except Exception:
            return False
        return True

    async def open(self, key: str) -> bytes:
        raise NotImplementedError("Use controlled document download streaming")

    async def delete(self, key: str) -> None:
        raise NotImplementedError("Governed SharePoint documents are never automatically deleted")

    async def metadata(self, key: str) -> EvidenceMetadata | None:
        site_id, drive_id, item_id = parse_sharepoint_storage_uri(key)
        if site_id != self.site_id:
            return None
        item = await self.client.get_drive_item(drive_id, item_id)
        return EvidenceMetadata(storage_uri=key, size_bytes=item.size, content_type=None)

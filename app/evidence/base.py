"""Evidence-store abstraction.

Milestone 2 ships a filesystem backend for local development and tests;
Milestone 3 replaces/extends it with SharePoint-backed controlled storage.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EvidenceWriteResult:
    storage_uri: str
    bytes_written: int
    sha256_checksum: str
    content_type: str
    site_id: str | None = None
    drive_id: str | None = None
    drive_item_id: str | None = None
    list_item_id: str | None = None
    web_url: str | None = None
    etag: str | None = None
    ctag: str | None = None
    upload_method: str | None = None
    version_id: str | None = None


@dataclass(frozen=True)
class EvidenceMetadata:
    storage_uri: str
    size_bytes: int
    content_type: str | None


class EvidenceStore(Protocol):
    async def put_bytes(
        self, key: str, data: bytes, *, content_type: str = "application/octet-stream"
    ) -> EvidenceWriteResult: ...

    async def put_stream(
        self,
        key: str,
        stream: AsyncIterator[bytes],
        *,
        max_bytes: int,
        content_type: str = "application/octet-stream",
    ) -> EvidenceWriteResult: ...

    async def exists(self, key: str) -> bool: ...

    async def open(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def metadata(self, key: str) -> EvidenceMetadata | None: ...

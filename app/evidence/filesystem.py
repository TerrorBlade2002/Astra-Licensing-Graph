"""Filesystem evidence store (local development and tests only).

Production startup rejects this backend via configuration validation.
Writes are atomic: content is streamed to a temporary file in the same
directory and renamed into place, hashing while streaming. All OS calls use
extended-length paths on Windows so deep evidence trees survive MAX_PATH.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from app.evidence.base import EvidenceMetadata, EvidenceWriteResult
from app.evidence.hashing import StreamingSha256
from app.graph.errors import EvidenceLimitExceededError


def _oslong(path: Path) -> str:
    """Extended-length path form for Windows OS calls (>260 chars)."""
    raw = str(path)
    if os.name == "nt" and not raw.startswith("\\\\?\\"):
        return "\\\\?\\" + raw
    return raw


class FilesystemEvidenceStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        os.makedirs(_oslong(self.root), exist_ok=True)

    def _resolve(self, key: str) -> Path:
        # Keys are internal ('mailboxes/<uuid>/emails/<uuid>/message.json'),
        # but resolve defensively anyway: the final path must stay inside root.
        candidate = (self.root / key).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError(f"Evidence key escapes the store root: {key!r}")
        return candidate

    def _to_uri(self, path: Path) -> str:
        return path.as_uri()

    async def put_bytes(
        self, key: str, data: bytes, *, content_type: str = "application/octet-stream"
    ) -> EvidenceWriteResult:
        async def _single() -> AsyncIterator[bytes]:
            yield data

        return await self.put_stream(
            key, _single(), max_bytes=max(len(data), 1), content_type=content_type
        )

    async def put_stream(
        self,
        key: str,
        stream: AsyncIterator[bytes],
        *,
        max_bytes: int,
        content_type: str = "application/octet-stream",
    ) -> EvidenceWriteResult:
        target = self._resolve(key)
        os.makedirs(_oslong(target.parent), exist_ok=True)
        tmp_path = target.parent / f".tmp-{uuid.uuid4().hex}"

        hasher = StreamingSha256()
        try:
            with open(_oslong(tmp_path), "wb") as fh:
                async for chunk in stream:
                    hasher.update(chunk)
                    if hasher.bytes_seen > max_bytes:
                        raise EvidenceLimitExceededError(
                            "Streamed content exceeded the configured size limit.",
                            details={"max_bytes": max_bytes},
                        )
                    fh.write(chunk)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(_oslong(tmp_path), _oslong(target))
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(_oslong(tmp_path))

        if os.name == "posix":
            target.chmod(0o600)

        return EvidenceWriteResult(
            storage_uri=self._to_uri(target),
            bytes_written=hasher.bytes_seen,
            sha256_checksum=hasher.hexdigest(),
            content_type=content_type,
        )

    async def exists(self, key: str) -> bool:
        return os.path.exists(_oslong(self._resolve(key)))

    async def open(self, key: str) -> bytes:
        with open(_oslong(self._resolve(key)), "rb") as fh:
            return fh.read()

    async def delete(self, key: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(_oslong(self._resolve(key)))

    async def metadata(self, key: str) -> EvidenceMetadata | None:
        path = self._resolve(key)
        try:
            stat = os.stat(_oslong(path))
        except FileNotFoundError:
            return None
        return EvidenceMetadata(
            storage_uri=self._to_uri(path),
            size_bytes=stat.st_size,
            content_type=None,
        )


def evidence_key_for_email(mailbox_id: str, email_id: str, filename: str) -> str:
    return f"mailboxes/{mailbox_id}/emails/{email_id}/{filename}"


def evidence_key_for_attachment(mailbox_id: str, email_id: str, stored_filename: str) -> str:
    return f"mailboxes/{mailbox_id}/emails/{email_id}/attachments/{stored_filename}"

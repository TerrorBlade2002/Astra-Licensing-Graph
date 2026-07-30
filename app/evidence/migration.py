"""Idempotent governed-evidence migration into SharePoint."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.sharepoint import SharePointEvidenceStore
from app.models import Document, DocumentVersion, SharePointDrive
from app.repositories.documents import DocumentRepository


@dataclass
class MigrationPlan:
    eligible: int = 0
    already_migrated: int = 0
    missing_source: int = 0
    hash_mismatch: int = 0
    unknown_route: int = 0
    estimated_bytes: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class EvidenceMigrationService:
    def __init__(self, session: AsyncSession, store: SharePointEvidenceStore) -> None:
        self.session = session
        self.store = store
        self.repo = DocumentRepository(session)

    async def plan(self) -> MigrationPlan:
        result = MigrationPlan()
        versions = list((await self.session.scalars(select(DocumentVersion))).all())
        for version in versions:
            if not version.graph_drive_item_id.startswith("pending:migration"):
                result.already_migrated += 1
                continue
            source = _file_path(version.source_storage_uri)
            if source is None or not source.is_file():
                result.missing_source += 1
                continue
            if _sha256(source) != version.content_sha256:
                result.hash_mismatch += 1
                continue
            drive = await self.session.scalar(
                select(SharePointDrive).where(
                    SharePointDrive.graph_drive_id == version.graph_drive_id,
                    SharePointDrive.is_active.is_(True),
                )
            )
            if not drive or not drive.root_drive_item_id:
                result.unknown_route += 1
                continue
            result.eligible += 1
            result.estimated_bytes += source.stat().st_size
        return result

    async def run(self) -> MigrationPlan:
        versions = list((await self.session.scalars(select(DocumentVersion))).all())
        for version in versions:
            if not version.graph_drive_item_id.startswith("pending:migration"):
                continue
            source = _file_path(version.source_storage_uri)
            if source is None or not source.is_file() or _sha256(source) != version.content_sha256:
                continue
            drive = await self.session.scalar(
                select(SharePointDrive).where(
                    SharePointDrive.graph_drive_id == version.graph_drive_id,
                    SharePointDrive.is_active.is_(True),
                )
            )
            if not drive or not drive.root_drive_item_id:
                continue

            # Bound as a default: the closure must read this iteration's file,
            # not whichever version the loop happens to be on when it runs.
            evidence_file: Path = source

            async def chunks(path: Path = evidence_file) -> AsyncIterator[bytes]:
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        yield chunk

            uploaded = await self.store.put_stream(
                f"{drive.graph_drive_id}/{drive.root_drive_item_id}/{version.filename}",
                chunks(),
                max_bytes=max(1, version.size_bytes),
                content_type=version.mime_type or "application/octet-stream",
            )
            if (
                uploaded.bytes_written != version.size_bytes
                or uploaded.sha256_checksum != version.content_sha256
            ):
                continue
            version.graph_drive_item_id = uploaded.drive_item_id or version.graph_drive_item_id
            version.graph_list_item_id = uploaded.list_item_id
            version.web_url = uploaded.web_url
            version.graph_etag = uploaded.etag
            version.graph_ctag = uploaded.ctag
            version.storage_status = "AVAILABLE"
            document = await self.session.get(Document, version.document_id)
            if document:
                document.current_version_id = version.id
                self.repo.add_event(
                    document.id,
                    "EVIDENCE_MIGRATED",
                    actor_type="SYSTEM",
                    actor_id="migrate-evidence",
                    note="Local source retained for the operator-defined rollback window.",
                )
            await self.session.commit()
        return await self.plan()


def _file_path(uri: str | None) -> Path | None:
    if not uri:
        return None
    parsed = urlsplit(uri)
    if parsed.scheme != "file":
        return None
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

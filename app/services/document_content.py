"""Fetch a document version's bytes, whichever store holds them.

Downloads, packet assembly, and form preparation all need the same thing: the
content of an approved version, copied into a temporary local store. They
should not each know which backend is configured, so that knowledge lives here
and switching `EVIDENCE_STORAGE_BACKEND` stays a one-variable change.
"""

from __future__ import annotations

from app.core.config import Settings
from app.evidence.base import EvidenceStore
from app.evidence.filesystem import FilesystemEvidenceStore
from app.evidence.r2 import R2EvidenceStore
from app.models import DocumentVersion
from app.services.document_upload import OBJECT_STORE_SITE_SENTINEL
from app.sharepoint.client import SharePointClient


def version_is_object_stored(version: DocumentVersion) -> bool:
    """True when this version's bytes live in an object store, not SharePoint."""
    return version.graph_site_id == OBJECT_STORE_SITE_SENTINEL


def source_store_for(settings: Settings) -> EvidenceStore:
    """The store that currently holds newly written document content."""
    if settings.evidence_storage_backend == "r2":
        return R2EvidenceStore(settings)
    return FilesystemEvidenceStore(settings.filesystem_evidence_root)


async def fetch_version_content(
    version: DocumentVersion,
    *,
    settings: Settings,
    sharepoint: SharePointClient | None,
    target: EvidenceStore,
    target_key: str,
    max_bytes: int,
) -> None:
    """Copy one version's content into ``target`` under ``target_key``.

    A version written to an object store keeps its object key in
    ``graph_drive_item_id``, so no lookup table is needed to find it again.
    """
    if version_is_object_stored(version):
        source = source_store_for(settings)
        data = await source.open(version.graph_drive_item_id)
        if len(data) > max_bytes:
            raise ValueError("Document version exceeds the download size limit.")
        await target.put_bytes(
            target_key, data, content_type=version.mime_type or "application/octet-stream"
        )
        return

    if sharepoint is None:
        raise ValueError(
            "This version is stored in SharePoint, which is not enabled in this environment."
        )
    await sharepoint.download_to_store(
        version.graph_drive_id,
        version.graph_drive_item_id,
        target,
        target_key,
        max_bytes=max_bytes,
    )

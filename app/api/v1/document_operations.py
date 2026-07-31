"""Upload, promotion, controlled download, and preview endpoints."""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.documents.authorization import DevelopmentDocumentAuthorization
from app.documents.enums import SourceType
from app.documents.naming import sanitize_download_filename
from app.evidence.base import EvidenceStore
from app.evidence.filesystem import FilesystemEvidenceStore
from app.evidence.r2 import R2EvidenceStore
from app.evidence.sharepoint import SharePointEvidenceStore
from app.graph.auth import MsalConfidentialClientTokenProvider
from app.graph.client import GraphHttpClient
from app.models import Document
from app.repositories.documents import DocumentRepository
from app.schemas.document import DocumentOut, PromoteAttachmentRequest, ReviewedDocumentMetadata
from app.services.document_catalog import DocumentCatalogService
from app.services.document_content import fetch_version_content
from app.services.document_promotion import DocumentPromotionService
from app.services.document_upload import DocumentUploadMetadata, DocumentUploadService
from app.sharepoint.client import SharePointClient

router = APIRouter(tags=["documents"])


def _metadata(value: ReviewedDocumentMetadata) -> DocumentUploadMetadata:
    return DocumentUploadMetadata(**value.model_dump())


def _clients(
    settings: SettingsDep,
) -> tuple[GraphHttpClient | None, SharePointClient | None, EvidenceStore]:
    """Clients for the *configured* storage backend.

    Document governance is independent of where bytes land, so an upload must
    follow ``EVIDENCE_STORAGE_BACKEND``. Requiring SharePoint here regardless
    made the repository unusable whenever SharePoint was unavailable or not yet
    provisioned — which is precisely when the fallback store is needed.
    """
    if settings.evidence_storage_backend == "r2":
        return None, None, R2EvidenceStore(settings)
    if settings.evidence_storage_backend == "filesystem":
        if settings.app_env not in ("local", "test"):
            raise HTTPException(
                status_code=503,
                detail="Filesystem document storage is not permitted in this environment.",
            )
        return None, None, FilesystemEvidenceStore(settings.filesystem_evidence_root)
    if not settings.sharepoint_enabled or not settings.sharepoint_site_id:
        raise HTTPException(status_code=503, detail="SharePoint repository is not enabled.")
    graph = GraphHttpClient(settings, MsalConfidentialClientTokenProvider(settings))
    sharepoint = SharePointClient(graph, settings)
    return (
        graph,
        sharepoint,
        SharePointEvidenceStore(sharepoint, site_id=settings.sharepoint_site_id),
    )


async def _aclose(*clients: GraphHttpClient | SharePointClient | None) -> None:
    """Close only the clients a backend actually created."""
    for client in clients:
        if client is not None:
            await client.aclose()


def _uploader(
    session: SessionDep, settings: SettingsDep, store: EvidenceStore
) -> DocumentUploadService:
    return DocumentUploadService(
        session,
        store,
        allowed_mime_types=settings.document_allowed_mime_types,
        allowed_extensions=settings.document_allowed_extensions,
        max_bytes=settings.document_max_bytes,
        filename_max_length=settings.document_filename_max_length,
    )


@router.post("/documents/uploads", response_model=DocumentOut, status_code=201)
async def manual_upload(
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
    file: UploadFile = File(...),
    metadata_json: str = Form(...),
    idempotency_key: str = Form(..., min_length=8, max_length=200),
) -> Document:
    if not DevelopmentDocumentAuthorization().can_upload_document(actor):
        raise HTTPException(status_code=403, detail="Document upload is not permitted.")
    try:
        metadata = ReviewedDocumentMetadata.model_validate(json.loads(metadata_json))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="Document metadata is invalid.") from exc
    size = 0
    path: Path
    try:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = Path(handle.name)
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.document_max_bytes:
                    raise HTTPException(status_code=413, detail="Document exceeds the size limit.")
                handle.write(chunk)
        graph, sharepoint, store = _clients(settings)
        try:
            outcome = await _uploader(session, settings, store).upload_path(
                path,
                original_filename=file.filename or "upload.bin",
                mime_type=file.content_type or "application/octet-stream",
                metadata=_metadata(metadata),
                source_type=SourceType.MANUAL_UPLOAD,
                actor_id=actor.actor_id or "unknown",
                idempotency_key=idempotency_key,
            )
        finally:
            await _aclose(sharepoint, graph)
    finally:
        path.unlink(missing_ok=True)
    return outcome.document


@router.post("/email-attachments/{attachment_id}/promote", response_model=DocumentOut)
async def promote_attachment(
    attachment_id: uuid.UUID,
    body: PromoteAttachmentRequest,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> Document:
    graph, sharepoint, store = _clients(settings)
    try:
        outcome = await DocumentPromotionService(
            session, _uploader(session, settings, store)
        ).promote(
            attachment_id,
            metadata=_metadata(body.metadata),
            actor_id=actor.actor_id or "unknown",
            idempotency_key=body.idempotency_key,
        )
    finally:
        await _aclose(sharepoint, graph)
    return outcome.document


async def _download(
    document_id: uuid.UUID,
    version_id: uuid.UUID | None,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> FileResponse:
    document = await DocumentCatalogService(session).require(document_id)
    if not DevelopmentDocumentAuthorization().can_download_document(actor, document):
        raise HTTPException(status_code=404, detail="Document not found.")
    target_version = version_id or document.current_version_id
    if target_version is None:
        raise HTTPException(status_code=409, detail="Document has no downloadable version.")
    version = await DocumentRepository(session).version(document.id, target_version)
    if version is None or version.storage_status != "AVAILABLE":
        raise HTTPException(status_code=404, detail="Document version is not available.")
    temp_root = Path(tempfile.mkdtemp(prefix="astra-document-download-"))
    store = FilesystemEvidenceStore(temp_root)
    graph, sharepoint, _sp_store = _clients(settings)
    try:
        await fetch_version_content(
            version,
            settings=settings,
            sharepoint=sharepoint,
            target=store,
            target_key="content",
            max_bytes=settings.document_download_max_bytes,
        )
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise
    finally:
        await _aclose(sharepoint, graph)
    DocumentRepository(session).add_event(
        document.id, "DOWNLOADED", actor_type="HUMAN", actor_id=actor.actor_id
    )
    await session.commit()
    response = FileResponse(
        temp_root / "content",
        media_type=version.mime_type or "application/octet-stream",
        filename=sanitize_download_filename(version.filename),
        background=BackgroundTask(_cleanup_directory, temp_root),
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


def _cleanup_directory(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


@router.get("/documents/{document_id}/download")
async def download_current(
    document_id: uuid.UUID, session: SessionDep, settings: SettingsDep, actor: ActorDep
) -> FileResponse:
    return await _download(document_id, None, session, settings, actor)


@router.get("/documents/{document_id}/versions/{version_id}/download")
async def download_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> FileResponse:
    return await _download(document_id, version_id, session, settings, actor)


@router.post("/documents/{document_id}/preview")
async def preview_document(
    document_id: uuid.UUID, session: SessionDep, settings: SettingsDep, actor: ActorDep
) -> dict[str, Any]:
    if not settings.document_preview_enabled:
        raise HTTPException(status_code=404, detail="Document preview is disabled.")
    document = await DocumentCatalogService(session).require(document_id)
    if not DevelopmentDocumentAuthorization().can_view_document(actor, document):
        raise HTTPException(status_code=404, detail="Document not found.")
    if not document.current_version_id:
        raise HTTPException(status_code=409, detail="Document has no current version.")
    version = await DocumentRepository(session).version(document.id, document.current_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found.")
    graph, sharepoint, _store = _clients(settings)
    if sharepoint is None:
        # Preview is a SharePoint rendering service. An object store has no
        # equivalent, and minting a public URL for one would bypass the
        # controlled-download path entirely.
        raise HTTPException(
            status_code=503,
            detail="Document preview requires the SharePoint repository.",
        )
    try:
        payload = await sharepoint.create_preview(
            version.graph_drive_id, version.graph_drive_item_id
        )
    finally:
        await _aclose(sharepoint, graph)
    url = payload.get("getUrl")
    if not url:
        raise HTTPException(status_code=502, detail="SharePoint did not return a preview.")
    return {"preview_url": url, "expires_with_session": True}

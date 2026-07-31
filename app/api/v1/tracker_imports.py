"""Safe dry-run-first master tracker import endpoints."""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.dependencies import SessionDep, SettingsDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.core.crypto import content_sha256
from app.core.exceptions import StateConflictError
from app.documents.enums import SourceType
from app.schemas.licensing import TrackerImportApply, TrackerImportApplyOut, TrackerImportPlanOut
from app.services.document_upload import DocumentUploadMetadata
from app.services.tracker_import_service import TrackerImportService

router = APIRouter(tags=["tracker-imports"])

AdminDep = Annotated[CurrentActor, Depends(require_role(Role.ADMIN))]


@router.post("/tracker-imports", response_model=TrackerImportPlanOut, status_code=201)
async def plan_import(
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
    file: UploadFile = File(...),
    mapping_json: str | None = Form(default=None),
    sheet_name: str | None = Form(default=None),
) -> dict[str, object]:
    content = await file.read(settings.tracker_import_max_bytes + 1)
    if len(content) > settings.tracker_import_max_bytes:
        raise StateConflictError("Tracker upload exceeds TRACKER_IMPORT_MAX_BYTES.")
    try:
        mapping = json.loads(mapping_json) if mapping_json else None
    except json.JSONDecodeError as exc:
        raise StateConflictError("mapping_json is not valid JSON.") from exc
    if mapping is not None and not isinstance(mapping, dict):
        raise StateConflictError("mapping_json must be an object of source-to-target columns.")
    source_document_id = None
    if settings.sharepoint_enabled:
        from app.api.v1.document_operations import _aclose, _clients, _uploader

        suffix = Path(file.filename or "tracker.csv").suffix or ".csv"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            source_path = Path(handle.name)
            handle.write(content)
        graph, sharepoint, store = _clients(settings)
        try:
            outcome = await _uploader(session, settings, store).upload_path(
                source_path,
                original_filename=file.filename or "tracker.csv",
                mime_type=file.content_type or "application/octet-stream",
                metadata=DocumentUploadMetadata(
                    canonical_title=f"Master tracker import: {file.filename or 'tracker'}",
                    document_type="MASTER_TRACKER",
                    confidentiality_level="CONFIDENTIAL",
                    reusable=False,
                ),
                source_type=SourceType.MANUAL_UPLOAD,
                actor_id=actor.actor_id,
                idempotency_key=f"tracker-source:{content_sha256(content)}",
            )
            source_document_id = outcome.document.id
        finally:
            source_path.unlink(missing_ok=True)
            await _aclose(sharepoint, graph)
    return await TrackerImportService(session, settings).plan(
        actor=actor,
        filename=file.filename or "tracker.csv",
        content=content,
        mapping=mapping,
        sheet_name=sheet_name,
        source_document_id=source_document_id,
    )


@router.get("/tracker-imports/{import_id}")
async def import_report(
    import_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> dict[str, object]:
    return await TrackerImportService(session, settings).report(import_id)


@router.post("/tracker-imports/{import_id}/apply", response_model=TrackerImportApplyOut)
async def apply_import(
    import_id: uuid.UUID,
    payload: TrackerImportApply,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> dict[str, object]:
    return await TrackerImportService(session, settings).apply(
        import_id, actor=actor, confirm=payload.confirm
    )

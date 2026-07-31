"""Document packet templates, building, immutable approval, and manifests."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from starlette.background import BackgroundTask

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.api.v1.document_operations import _aclose, _cleanup_directory, _clients
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.core.exceptions import NotFoundError, StateConflictError
from app.documents.naming import sanitize_download_filename
from app.evidence.filesystem import FilesystemEvidenceStore
from app.licensing.audit import add_licensing_audit
from app.licensing.jobs import LicensingJobType
from app.models import (
    DocumentPacket,
    PacketTemplate,
    PacketTemplateItem,
    RequirementSourceSnapshot,
)
from app.repositories.licensing_jobs import LicensingJobRepository
from app.schemas.licensing import (
    PacketBuild,
    PacketCreate,
    PacketDetailOut,
    PacketReject,
    PacketTemplateCreate,
)
from app.services.document_packet_service import DocumentPacketService
from app.sharepoint.urls import parse_sharepoint_storage_uri

router = APIRouter(tags=["document-packets"])

AnalystDep = Annotated[CurrentActor, Depends(require_role(Role.ANALYST))]
ReviewerDep = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]
AdminDep = Annotated[CurrentActor, Depends(require_role(Role.ADMIN))]


@router.get("/packet-templates")
async def list_templates(session: SessionDep, actor: ActorDep) -> list[dict[str, object]]:
    templates = list(await session.scalars(select(PacketTemplate).order_by(PacketTemplate.name)))
    return [
        {
            "id": str(row.id),
            "template_key": row.template_key,
            "name": row.name,
            "status": row.status,
            "jurisdiction_id": str(row.jurisdiction_id) if row.jurisdiction_id else None,
            "license_type_id": str(row.license_type_id) if row.license_type_id else None,
            "case_type": row.case_type,
        }
        for row in templates
    ]


@router.post("/packet-templates", status_code=201)
async def create_template(
    payload: PacketTemplateCreate,
    session: SessionDep,
    actor: AdminDep,
) -> dict[str, str]:
    if payload.requirement_source_snapshot_id:
        snapshot = await session.get(
            RequirementSourceSnapshot, payload.requirement_source_snapshot_id
        )
        if snapshot is None or snapshot.review_status not in (
            "APPROVED",
            "SUPERSEDED",
        ):
            raise StateConflictError(
                "A packet template checklist must cite an approved source snapshot."
            )
    if not payload.items:
        raise StateConflictError("A packet template requires at least one checklist item.")
    template = PacketTemplate(
        template_key=payload.template_key,
        name=payload.name,
        jurisdiction_id=payload.jurisdiction_id,
        license_type_id=payload.license_type_id,
        case_type=payload.case_type,
        description=payload.description,
        requirement_source_snapshot_id=payload.requirement_source_snapshot_id,
        status="ACTIVE",
    )
    session.add(template)
    await session.flush()
    for item in payload.items:
        session.add(
            PacketTemplateItem(
                packet_template_id=template.id,
                item_key=item.item_key,
                document_type=item.document_type,
                required=item.required,
                selection_policy=item.selection_policy or {},
                sort_order=item.sort_order,
                instructions=item.instructions,
            )
        )
    await session.commit()
    return {"id": str(template.id), "template_key": template.template_key}


@router.get("/document-packets")
async def list_packets(
    session: SessionDep,
    actor: ActorDep,
    case_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[dict[str, object]]:
    stmt = select(DocumentPacket).order_by(DocumentPacket.created_at.desc())
    if case_id:
        stmt = stmt.where(DocumentPacket.compliance_case_id == case_id)
    if status:
        stmt = stmt.where(DocumentPacket.status == status)
    rows = list(await session.scalars(stmt))
    return [
        {
            "id": str(row.id),
            "packet_key": row.packet_key,
            "compliance_case_id": str(row.compliance_case_id),
            "version": row.version,
            "status": row.status,
            "manifest_sha256": row.manifest_sha256,
        }
        for row in rows
    ]


@router.post("/compliance-cases/{case_id}/document-packets", status_code=201)
async def create_packet(
    case_id: uuid.UUID,
    payload: PacketCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> dict[str, str]:
    packet = await DocumentPacketService(session, settings).create_packet(
        case_id, actor=actor, packet_template_id=payload.packet_template_id
    )
    return {"id": str(packet.id), "status": packet.status}


@router.get("/document-packets/{packet_id}", response_model=PacketDetailOut)
async def get_packet(
    packet_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> dict[str, object]:
    return await DocumentPacketService(session, settings).detail(packet_id)


@router.post("/document-packets/{packet_id}/build", response_model=PacketDetailOut)
async def build_packet(
    packet_id: uuid.UUID,
    payload: PacketBuild,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> dict[str, object]:
    service = DocumentPacketService(session, settings)
    packet = await service.build(packet_id, actor=actor, overrides=payload.overrides, commit=False)
    if settings.packet_archive_format == "ZIP":
        await LicensingJobRepository(session).enqueue(
            job_type=LicensingJobType.BUILD_DOCUMENT_PACKET,
            idempotency_key=f"packet-archive:{packet.id}:{packet.manifest_sha256}",
            payload={
                "packet_id": str(packet.id),
                "requested_by_actor": actor.actor_id,
                "manifest_sha256": packet.manifest_sha256,
            },
            compliance_case_id=packet.compliance_case_id,
        )
    await session.commit()
    return await service.detail(packet_id)


@router.post("/document-packets/{packet_id}/approve", response_model=PacketDetailOut)
async def approve_packet(
    packet_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> dict[str, object]:
    service = DocumentPacketService(session, settings)
    await service.approve(packet_id, actor=actor)
    return await service.detail(packet_id)


@router.post("/document-packets/{packet_id}/reject", response_model=PacketDetailOut)
async def reject_packet(
    packet_id: uuid.UUID,
    payload: PacketReject,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> dict[str, object]:
    service = DocumentPacketService(session, settings)
    await service.reject(packet_id, actor=actor, reason=payload.reason)
    return await service.detail(packet_id)


@router.get("/document-packets/{packet_id}/download")
async def download_archive(
    packet_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> FileResponse:
    """Download the approved governed ZIP without exposing a Graph URL."""
    packet = await session.get(DocumentPacket, packet_id)
    if packet is None:
        raise NotFoundError("Packet not found.")
    if packet.status != "APPROVED":
        raise StateConflictError("Only an approved immutable packet can be downloaded.")
    if not packet.archive_storage_uri or not packet.archive_sha256:
        raise StateConflictError("The governed packet archive is not available.")

    temporary_root: Path | None = None
    parsed = urlsplit(packet.archive_storage_uri)
    if parsed.scheme == "sharepoint":
        _site_id, drive_id, item_id = parse_sharepoint_storage_uri(packet.archive_storage_uri)
        temporary_root = Path(tempfile.mkdtemp(prefix="astra-packet-download-"))
        local_store = FilesystemEvidenceStore(temporary_root)
        graph, sharepoint, _store = _clients(settings)
        try:
            assert sharepoint is not None  # scheme is sharepoint, so the client exists
            result = await sharepoint.download_to_store(
                drive_id,
                item_id,
                local_store,
                "packet.zip",
                max_bytes=settings.packet_max_total_bytes,
            )
            path = temporary_root / "packet.zip"
            actual_hash = result.sha256_checksum
        except Exception:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise
        finally:
            await _aclose(sharepoint, graph)
    elif parsed.scheme == "file" and settings.evidence_storage_backend == "filesystem":
        raw_path = unquote(parsed.path)
        if os.name == "nt" and raw_path.startswith("/"):
            raw_path = raw_path[1:]
        path = Path(raw_path).resolve()
        evidence_root = Path(settings.filesystem_evidence_root).resolve()
        if not path.is_relative_to(evidence_root) or not path.is_file():
            raise NotFoundError("The packet archive is not available.")
        with path.open("rb") as handle:
            actual_hash = hashlib.file_digest(handle, "sha256").hexdigest()
    else:
        raise NotFoundError("The packet archive storage reference is unsupported.")

    if actual_hash.lower() != packet.archive_sha256.lower():
        if temporary_root:
            shutil.rmtree(temporary_root, ignore_errors=True)
        raise StateConflictError("The stored packet archive failed integrity verification.")
    add_licensing_audit(
        session,
        actor=actor,
        entity_type="document_packet",
        entity_id=packet.id,
        action="packet_archive_downloaded",
        after={
            "manifest_sha256": packet.manifest_sha256,
            "archive_sha256": packet.archive_sha256,
        },
    )
    await session.commit()
    response = FileResponse(
        path,
        media_type="application/zip",
        filename=sanitize_download_filename(f"{packet.packet_key}-v{packet.version}.zip"),
        background=(BackgroundTask(_cleanup_directory, temporary_root) if temporary_root else None),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/document-packets/{packet_id}/manifest")
async def download_manifest(
    packet_id: uuid.UUID,
    session: SessionDep,
    actor: ActorDep,
) -> JSONResponse:
    packet = await session.get(DocumentPacket, packet_id)
    if packet is None:
        raise NotFoundError("Packet not found.")
    response = JSONResponse(
        {
            "packet_key": packet.packet_key,
            "version": packet.version,
            "status": packet.status,
            "manifest_sha256": packet.manifest_sha256,
            "manifest": packet.manifest,
        }
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{packet.packet_key}-manifest.json"'
    )
    return response

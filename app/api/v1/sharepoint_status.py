"""Sanitized SharePoint repository operations and status."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.documents.authorization import DevelopmentDocumentAuthorization
from app.documents.enums import DocumentJobStatus, DocumentJobType
from app.models import DocumentJob, SharePointDrive, SharePointSite, SharePointSyncState
from app.repositories.document_jobs import DocumentJobRepository

router = APIRouter(prefix="/integrations/sharepoint", tags=["sharepoint"])


@router.get("/status")
async def sharepoint_status(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    site = await session.scalar(select(SharePointSite).where(SharePointSite.is_active.is_(True)))
    drive_count = await session.scalar(
        select(func.count(SharePointDrive.id)).where(SharePointDrive.is_active.is_(True))
    )
    pending = await session.scalar(
        select(func.count(DocumentJob.id)).where(
            DocumentJob.status.in_(
                [DocumentJobStatus.PENDING.value, DocumentJobStatus.FAILED_RETRYABLE.value]
            )
        )
    )
    failed = await session.scalar(
        select(func.count(DocumentJob.id)).where(
            DocumentJob.status == DocumentJobStatus.FAILED_REVIEW.value
        )
    )
    return {
        "sharepoint_enabled": settings.sharepoint_enabled,
        "permission_mode": settings.sharepoint_permission_mode,
        "site_cataloged": site is not None,
        "site_id": site.graph_site_id if site else settings.sharepoint_site_id,
        "active_drives": int(drive_count or 0),
        "pending_document_jobs": int(pending or 0),
        "failed_review_document_jobs": int(failed or 0),
    }


storage_router = APIRouter(prefix="/integrations/storage", tags=["storage"])


@storage_router.get("/status")
async def storage_status(settings: SettingsDep) -> dict[str, Any]:
    """Where governed document content is written, without exposing credentials.

    SharePoint stays the repository of record; R2 is the fallback object store.
    Only the backend name, bucket, and whether credentials are present are
    reported — never a key, secret, or signed URL.
    """
    backend = settings.evidence_storage_backend
    detail: dict[str, Any] = {"backend": backend}
    if backend == "r2":
        detail |= {
            "bucket": settings.r2_bucket,
            "endpoint_host": (
                settings.r2_endpoint_url.split("://", 1)[-1] if settings.r2_endpoint_url else None
            ),
            "credentials_configured": bool(
                settings.r2_access_key_id and settings.r2_secret_access_key
            ),
        }
    elif backend == "sharepoint":
        detail |= {
            "site_id": settings.sharepoint_site_id,
            "permission_mode": settings.sharepoint_permission_mode,
        }
    else:
        detail |= {"root": settings.filesystem_evidence_root}
    return detail


@router.get("/drives")
async def list_sharepoint_drives(session: SessionDep) -> list[dict[str, Any]]:
    drives = list(
        (await session.scalars(select(SharePointDrive).order_by(SharePointDrive.purpose))).all()
    )
    result = []
    for drive in drives:
        sync = await session.scalar(
            select(SharePointSyncState).where(SharePointSyncState.drive_id == drive.id)
        )
        result.append(
            {
                "id": str(drive.id),
                "graph_drive_id": drive.graph_drive_id,
                "display_name": drive.display_name,
                "purpose": drive.purpose,
                "is_active": drive.is_active,
                "last_reconciled_at": sync.last_completed_at.isoformat()
                if sync and sync.last_completed_at
                else None,
                "delta_checkpoint_present": bool(sync and sync.delta_link),
                "needs_rebaseline": bool(sync and sync.needs_rebaseline),
            }
        )
    return result


@router.get("/jobs")
async def list_document_jobs(session: SessionDep, limit: int = 100) -> list[dict[str, Any]]:
    jobs = list(
        (
            await session.scalars(
                select(DocumentJob)
                .order_by(DocumentJob.created_at.desc())
                .limit(min(max(limit, 1), 200))
            )
        ).all()
    )
    return [
        {
            "id": str(job.id),
            "job_type": job.job_type,
            "status": job.status,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "available_at": job.available_at.isoformat(),
            "last_error_code": job.last_error_code,
            "created_at": job.created_at.isoformat(),
        }
        for job in jobs
    ]


async def _require_admin(settings: SettingsDep, actor: ActorDep) -> None:
    if settings.app_env == "production":
        raise HTTPException(
            status_code=403, detail="Administrative mutation is disabled in production."
        )
    if not DevelopmentDocumentAuthorization().can_manage_repository(actor):
        raise HTTPException(status_code=403, detail="Repository administration is not permitted.")


@router.post("/bootstrap", status_code=202)
async def enqueue_bootstrap(
    session: SessionDep, settings: SettingsDep, actor: ActorDep
) -> dict[str, Any]:
    await _require_admin(settings, actor)
    job, created = await DocumentJobRepository(session).enqueue(
        job_type=DocumentJobType.BOOTSTRAP_REPOSITORY,
        idempotency_key="bootstrap-repository",
        payload={"requested_by": actor.actor_id},
    )
    await session.commit()
    return {"job_id": str(job.id), "created": created, "status": job.status}


@router.post("/drives/{drive_id}/reconcile", status_code=202)
async def enqueue_reconcile(
    drive_id: uuid.UUID, session: SessionDep, settings: SettingsDep, actor: ActorDep
) -> dict[str, Any]:
    await _require_admin(settings, actor)
    drive = await session.get(SharePointDrive, drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="SharePoint drive not found.")
    job, created = await DocumentJobRepository(session).enqueue(
        job_type=DocumentJobType.RECONCILE_DRIVE,
        idempotency_key=f"reconcile:{drive_id}:{uuid.uuid4().hex[:8]}",
        drive_id=drive_id,
        payload={"requested_by": actor.actor_id},
    )
    await session.commit()
    return {"job_id": str(job.id), "created": created, "status": job.status}

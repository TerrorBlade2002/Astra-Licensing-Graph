"""Versioned requirement-source governance endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.core.crypto import content_sha256
from app.core.exceptions import NotFoundError, StateConflictError
from app.licensing.jobs import LicensingJobType
from app.models import RequirementSource, RequirementSourceSnapshot
from app.repositories.licensing_jobs import LicensingJobRepository
from app.schemas.licensing import (
    SnapshotCreate,
    SnapshotOut,
    SnapshotReview,
    SourceCreate,
    SourceOut,
)
from app.services.requirement_source_service import RequirementSourceService

router = APIRouter(tags=["requirement-sources"])

AdminDep = Annotated[CurrentActor, Depends(require_role(Role.ADMIN))]
ManagerDep = Annotated[CurrentActor, Depends(require_role(Role.MANAGER))]


class SourceFetchRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=200)


@router.get("/requirement-sources", response_model=list[SourceOut])
async def list_sources(
    session: SessionDep,
    actor: ActorDep,
    source_type: str | None = None,
    verification_status: str | None = None,
) -> list[RequirementSource]:
    stmt = select(RequirementSource).order_by(RequirementSource.title)
    if source_type:
        stmt = stmt.where(RequirementSource.source_type == source_type)
    if verification_status:
        stmt = stmt.where(RequirementSource.verification_status == verification_status)
    return list(await session.scalars(stmt))


@router.post("/requirement-sources", response_model=SourceOut, status_code=201)
async def create_source(
    payload: SourceCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> RequirementSource:
    return await RequirementSourceService(session, settings).register_source(
        actor=actor, **payload.model_dump(exclude_none=True)
    )


@router.get("/requirement-sources/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> RequirementSource:
    source = await session.get(RequirementSource, source_id)
    if source is None:
        raise NotFoundError("Requirement source not found.")
    return source


@router.get("/requirement-sources/{source_id}/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(
    source_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[RequirementSourceSnapshot]:
    return list(
        await session.scalars(
            select(RequirementSourceSnapshot)
            .where(RequirementSourceSnapshot.requirement_source_id == source_id)
            .order_by(RequirementSourceSnapshot.version.desc())
        )
    )


@router.post("/requirement-sources/{source_id}/fetch", status_code=202)
async def queue_public_fetch(
    source_id: uuid.UUID,
    payload: SourceFetchRequest,
    session: SessionDep,
    actor: AdminDep,
) -> dict[str, object]:
    source = await session.get(RequirementSource, source_id)
    if source is None:
        raise NotFoundError("Requirement source not found.")
    job, created = await LicensingJobRepository(session).enqueue(
        job_type=LicensingJobType.FETCH_REQUIREMENT_SOURCE,
        idempotency_key=f"source-fetch:{source_id}:{payload.idempotency_key}",
        payload={"source_id": str(source_id), "requested_by_actor": actor.actor_id},
    )
    await session.commit()
    return {"job_id": str(job.id), "created": created, "status": job.status}


@router.post(
    "/requirement-sources/{source_id}/snapshots",
    response_model=SnapshotOut,
    status_code=201,
)
async def add_snapshot(
    source_id: uuid.UUID,
    payload: SnapshotCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> RequirementSourceSnapshot:
    if not payload.content_storage_uri:
        raise StateConflictError(
            "Manual snapshots must already be preserved in governed storage. "
            "Use the allow-listed fetch job or provide its controlled storage URI."
        )
    storage_scheme = urlsplit(payload.content_storage_uri).scheme
    if storage_scheme != "sharepoint" and not (
        storage_scheme == "file"
        and settings.evidence_storage_backend == "filesystem"
        and settings.app_env in ("local", "test")
    ):
        raise StateConflictError(
            "Snapshot storage must be a governed SharePoint URI "
            "(or a local test evidence URI outside production)."
        )
    if (
        payload.content_text is not None
        and payload.content_sha256
        and content_sha256(payload.content_text.encode("utf-8")) != payload.content_sha256
    ):
        raise StateConflictError("The supplied content hash does not match the snapshot text.")
    snapshot, changed = await RequirementSourceService(session, settings).add_snapshot(
        source_id,
        actor=actor,
        content=payload.content_text.encode("utf-8") if payload.content_text else None,
        content_sha256_value=payload.content_sha256,
        content_storage_uri=payload.content_storage_uri,
        extracted_text=payload.content_text,
        effective_date=payload.effective_date,
        change_summary=payload.change_summary,
        commit=False,
    )
    if changed:
        await LicensingJobRepository(session).enqueue(
            job_type=LicensingJobType.COMPARE_SOURCE_SNAPSHOT,
            idempotency_key=f"source-compare:{snapshot.id}:{snapshot.content_sha256}",
            payload={
                "snapshot_id": str(snapshot.id),
                "requested_by_actor": actor.actor_id,
            },
        )
    await session.commit()
    return snapshot


@router.post(
    "/requirement-source-snapshots/{snapshot_id}/approve",
    response_model=SnapshotOut,
)
async def review_snapshot(
    snapshot_id: uuid.UUID,
    payload: SnapshotReview,
    session: SessionDep,
    settings: SettingsDep,
    actor: ManagerDep,
) -> RequirementSourceSnapshot:
    return await RequirementSourceService(session, settings).review_snapshot(
        snapshot_id, actor=actor, **payload.model_dump()
    )


@router.get("/requirement-source-snapshots/{snapshot_id}/diff")
async def snapshot_diff(
    snapshot_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> dict[str, object]:
    return await RequirementSourceService(session, settings).diff(snapshot_id)


@router.get("/requirement-sources/freshness/report")
async def freshness_report(
    session: SessionDep,
    settings: SettingsDep,
    actor: ManagerDep,
    notify_owners: bool = False,
) -> list[dict[str, object]]:
    return await RequirementSourceService(session, settings).freshness_report(
        notify_owners=notify_owners
    )

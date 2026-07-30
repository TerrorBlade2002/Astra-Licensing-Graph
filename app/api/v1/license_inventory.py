"""Licence inventory endpoints."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.dependencies import ActorDep, SessionDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.core.exceptions import NotFoundError
from app.licensing.audit import add_licensing_audit
from app.models import LegalEntity, LicenseBond, LicenseInventory, LicenseStatusEvent
from app.models.mixins import utcnow
from app.schemas.licensing import (
    BondCreate,
    BondOut,
    BondUpdate,
    LicenseCreate,
    LicenseListOut,
    LicenseOut,
    LicenseRenewedEvidence,
    LicenseStatusEventOut,
    LicenseTransition,
    LicenseUpdate,
    PageMeta,
)
from app.services.license_inventory_service import LicenseInventoryService

router = APIRouter(prefix="/licenses", tags=["license-inventory"])

AnalystDep = Annotated[CurrentActor, Depends(require_role(Role.ANALYST))]
ReviewerDep = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]


@router.get("", response_model=LicenseListOut)
async def list_licenses(
    session: SessionDep,
    actor: ActorDep,
    legal_entity_id: Annotated[uuid.UUID | None, Query()] = None,
    jurisdiction_id: Annotated[uuid.UUID | None, Query()] = None,
    license_type_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    filing_channel: Annotated[str | None, Query()] = None,
    owner: Annotated[str | None, Query()] = None,
    expiring_within_days: Annotated[int | None, Query(ge=0, le=3650)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LicenseListOut:
    filters = []
    if legal_entity_id:
        filters.append(LicenseInventory.legal_entity_id == legal_entity_id)
    if jurisdiction_id:
        filters.append(LicenseInventory.jurisdiction_id == jurisdiction_id)
    if license_type_id:
        filters.append(LicenseInventory.license_type_id == license_type_id)
    if status:
        filters.append(LicenseInventory.current_status == status)
    if filing_channel:
        filters.append(LicenseInventory.filing_channel == filing_channel)
    if owner:
        filters.append(LicenseInventory.responsible_owner == owner)
    if expiring_within_days is not None:
        horizon = date.today() + timedelta(days=expiring_within_days)
        filters.append(LicenseInventory.expiration_date.is_not(None))
        filters.append(LicenseInventory.expiration_date <= horizon)

    total = (
        await session.scalar(select(func.count()).select_from(LicenseInventory).where(*filters))
        or 0
    )
    rows = list(
        await session.scalars(
            select(LicenseInventory)
            .where(*filters)
            .order_by(LicenseInventory.expiration_date.nulls_last(), LicenseInventory.license_key)
            .limit(limit)
            .offset(offset)
        )
    )
    return LicenseListOut(
        items=[LicenseOut.model_validate(row) for row in rows],
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )


@router.post("", response_model=LicenseOut, status_code=201)
async def create_license(
    payload: LicenseCreate, session: SessionDep, actor: AnalystDep
) -> LicenseInventory:
    data = payload.model_dump(exclude_none=True)
    return await LicenseInventoryService(session).create_license(
        actor=actor,
        legal_entity_id=data.pop("legal_entity_id"),
        jurisdiction_id=data.pop("jurisdiction_id"),
        license_type_id=data.pop("license_type_id"),
        **data,
    )


@router.get("/{license_id}", response_model=LicenseOut)
async def get_license(
    license_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> LicenseInventory:
    record = await session.get(LicenseInventory, license_id)
    if record is None:
        raise NotFoundError("Licence not found.")
    return record


@router.patch("/{license_id}", response_model=LicenseOut)
async def update_license(
    license_id: uuid.UUID, payload: LicenseUpdate, session: SessionDep, actor: AnalystDep
) -> LicenseInventory:
    return await LicenseInventoryService(session).update_license(
        license_id, actor=actor, **payload.model_dump(exclude_unset=True)
    )


@router.get("/{license_id}/events", response_model=list[LicenseStatusEventOut])
async def list_license_events(
    license_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[LicenseStatusEvent]:
    return list(
        await session.scalars(
            select(LicenseStatusEvent)
            .where(LicenseStatusEvent.license_id == license_id)
            .order_by(LicenseStatusEvent.occurred_at)
        )
    )


@router.post("/{license_id}/transition", response_model=LicenseOut)
async def transition_license(
    license_id: uuid.UUID,
    payload: LicenseTransition,
    session: SessionDep,
    actor: AnalystDep,
) -> LicenseInventory:
    return await LicenseInventoryService(session).transition_status(
        license_id,
        to_status=payload.to_status,
        actor=actor,
        source_type=payload.source_type,
        source_reference=payload.source_reference,
        note=payload.note,
        effective_at=payload.effective_at,
    )


@router.post("/{license_id}/renewed-evidence", response_model=LicenseOut)
async def record_renewed_evidence(
    license_id: uuid.UUID,
    payload: LicenseRenewedEvidence,
    session: SessionDep,
    actor: ReviewerDep,
) -> LicenseInventory:
    """Apply renewed evidence, returning the licence to ACTIVE."""
    return await LicenseInventoryService(session).record_renewed_evidence(
        license_id,
        actor=actor,
        new_expiration_date=payload.new_expiration_date,
        new_issue_date=payload.new_issue_date,
        license_number=payload.license_number,
        evidence_document_id=payload.evidence_document_id,
    )


@router.get("/{license_id}/bonds", response_model=list[BondOut])
async def list_license_bonds(
    license_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[LicenseBond]:
    return list(
        await session.scalars(
            select(LicenseBond)
            .where(LicenseBond.license_id == license_id)
            .order_by(LicenseBond.expiration_date.nulls_last())
        )
    )


@router.post("/{license_id}/bonds", response_model=BondOut, status_code=201)
async def create_license_bond(
    license_id: uuid.UUID,
    payload: BondCreate,
    session: SessionDep,
    actor: AnalystDep,
) -> LicenseBond:
    license_record = await session.get(LicenseInventory, license_id)
    entity = await session.get(LegalEntity, payload.legal_entity_id)
    if license_record is None or entity is None:
        raise NotFoundError("License or legal entity not found.")
    if license_record.legal_entity_id != payload.legal_entity_id:
        from app.core.exceptions import StateConflictError

        raise StateConflictError("The bond and license must belong to the same legal entity.")
    fields = payload.model_dump(exclude_none=True)
    fields["license_id"] = license_id
    bond = LicenseBond(
        bond_key=f"{license_record.license_key}-bond-{uuid.uuid4().hex[:8]}",
        **fields,
    )
    session.add(bond)
    await session.flush()
    add_licensing_audit(
        session,
        actor=actor,
        entity_type="license_bond",
        entity_id=bond.id,
        action="bond_created",
        after={"status": bond.status, "bond_channel": bond.bond_channel},
    )
    await session.commit()
    return bond


@router.patch("/bonds/{bond_id}", response_model=BondOut)
async def update_bond(
    bond_id: uuid.UUID,
    payload: BondUpdate,
    session: SessionDep,
    actor: AnalystDep,
) -> LicenseBond:
    bond = await session.get(LicenseBond, bond_id)
    if bond is None:
        raise NotFoundError("Bond not found.")
    before = {"status": bond.status, "bond_channel": bond.bond_channel}
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(bond, field, value)
    bond.last_verified_at = utcnow()
    add_licensing_audit(
        session,
        actor=actor,
        entity_type="license_bond",
        entity_id=bond.id,
        action="bond_updated",
        before=before,
        after={"status": bond.status, "bond_channel": bond.bond_channel},
    )
    await session.commit()
    return bond

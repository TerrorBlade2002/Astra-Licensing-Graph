"""Legal entities, operating profiles, and licensing taxonomy endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import ActorDep, SessionDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.core.exceptions import NotFoundError
from app.models import BusinessActivity, Jurisdiction, LegalEntity, LicenseType, OperatingProfile
from app.schemas.licensing import (
    BusinessActivityOut,
    JurisdictionCreate,
    JurisdictionOut,
    LegalEntityCreate,
    LegalEntityOut,
    LegalEntityUpdate,
    LicenseTypeCreate,
    LicenseTypeOut,
    OperatingProfileCreate,
    OperatingProfileOut,
)
from app.services.license_inventory_service import LicenseInventoryService

router = APIRouter(tags=["licensing"])

AnalystDep = Annotated[CurrentActor, Depends(require_role(Role.ANALYST))]
ManagerDep = Annotated[CurrentActor, Depends(require_role(Role.MANAGER))]
ReviewerDep = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]
AdminDep = Annotated[CurrentActor, Depends(require_role(Role.ADMIN))]


@router.get("/legal-entities", response_model=list[LegalEntityOut])
async def list_legal_entities(
    session: SessionDep,
    actor: ActorDep,
    in_scope: Annotated[bool | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
) -> list[LegalEntity]:
    from sqlalchemy import select

    stmt = select(LegalEntity).order_by(LegalEntity.legal_name)
    if in_scope is not None:
        stmt = stmt.where(LegalEntity.is_in_scope.is_(in_scope))
    if status:
        stmt = stmt.where(LegalEntity.status == status)
    return list(await session.scalars(stmt))


@router.post("/legal-entities", response_model=LegalEntityOut, status_code=201)
async def create_legal_entity(
    payload: LegalEntityCreate, session: SessionDep, actor: ManagerDep
) -> LegalEntity:
    return await LicenseInventoryService(session).create_legal_entity(
        actor=actor, **payload.model_dump(exclude_none=True)
    )


@router.get("/legal-entities/{entity_id}", response_model=LegalEntityOut)
async def get_legal_entity(
    entity_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> LegalEntity:
    entity = await session.get(LegalEntity, entity_id)
    if entity is None:
        raise NotFoundError("Legal entity not found.")
    return entity


@router.patch("/legal-entities/{entity_id}", response_model=LegalEntityOut)
async def update_legal_entity(
    entity_id: uuid.UUID, payload: LegalEntityUpdate, session: SessionDep, actor: ManagerDep
) -> LegalEntity:
    return await LicenseInventoryService(session).update_legal_entity(
        entity_id, actor=actor, **payload.model_dump(exclude_unset=True)
    )


@router.get(
    "/legal-entities/{entity_id}/operating-profiles", response_model=list[OperatingProfileOut]
)
async def list_operating_profiles(
    entity_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[OperatingProfile]:
    from sqlalchemy import select

    return list(
        await session.scalars(
            select(OperatingProfile)
            .where(OperatingProfile.legal_entity_id == entity_id)
            .order_by(OperatingProfile.name, OperatingProfile.version.desc())
        )
    )


@router.post(
    "/legal-entities/{entity_id}/operating-profiles",
    response_model=OperatingProfileOut,
    status_code=201,
)
async def create_operating_profile(
    entity_id: uuid.UUID,
    payload: OperatingProfileCreate,
    session: SessionDep,
    actor: AnalystDep,
) -> OperatingProfile:
    return await LicenseInventoryService(session).create_operating_profile(
        entity_id,
        name=payload.name,
        facts=payload.facts,
        effective_from=payload.effective_from,
        actor=actor,
    )


@router.post("/operating-profiles/{profile_id}/approve", response_model=OperatingProfileOut)
async def approve_operating_profile(
    profile_id: uuid.UUID, session: SessionDep, actor: ReviewerDep
) -> OperatingProfile:
    return await LicenseInventoryService(session).approve_operating_profile(profile_id, actor=actor)


# --------------------------------------------------------------------- taxonomy


@router.get("/jurisdictions", response_model=list[JurisdictionOut])
async def list_jurisdictions(session: SessionDep, actor: ActorDep) -> list[Jurisdiction]:
    from sqlalchemy import select

    return list(await session.scalars(select(Jurisdiction).order_by(Jurisdiction.name)))


@router.post("/jurisdictions", response_model=JurisdictionOut, status_code=201)
async def create_jurisdiction(
    payload: JurisdictionCreate, session: SessionDep, actor: AdminDep
) -> Jurisdiction:
    jurisdiction = Jurisdiction(**payload.model_dump(exclude_none=True))
    session.add(jurisdiction)
    await session.commit()
    return jurisdiction


@router.get("/license-types", response_model=list[LicenseTypeOut])
async def list_license_types(session: SessionDep, actor: ActorDep) -> list[LicenseType]:
    from sqlalchemy import select

    return list(await session.scalars(select(LicenseType).order_by(LicenseType.name)))


@router.post("/license-types", response_model=LicenseTypeOut, status_code=201)
async def create_license_type(
    payload: LicenseTypeCreate, session: SessionDep, actor: AdminDep
) -> LicenseType:
    license_type = LicenseType(**payload.model_dump(exclude_none=True))
    session.add(license_type)
    await session.commit()
    return license_type


@router.get("/business-activities", response_model=list[BusinessActivityOut])
async def list_business_activities(session: SessionDep, actor: ActorDep) -> list[BusinessActivity]:
    from sqlalchemy import select

    return list(
        await session.scalars(
            select(BusinessActivity)
            .where(BusinessActivity.is_active.is_(True))
            .order_by(BusinessActivity.name)
        )
    )

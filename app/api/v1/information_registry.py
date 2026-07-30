"""Encrypted, versioned reusable-information registry endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_any_role, require_role
from app.auth.roles import Role
from app.core.exceptions import NotFoundError
from app.models import InformationDefinition, InformationValue
from app.schemas.licensing import (
    DefinitionCreate,
    DefinitionOut,
    InformationValueOut,
    OwnerAssignmentCreate,
    ValueApprove,
    ValueCreate,
    ValueReject,
)
from app.services.information_registry_service import InformationRegistryService

router = APIRouter(tags=["information-registry"])

AnalystDep = Annotated[CurrentActor, Depends(require_role(Role.ANALYST))]
ReviewerDep = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]
ManagerDep = Annotated[CurrentActor, Depends(require_role(Role.MANAGER))]
AdminDep = Annotated[CurrentActor, Depends(require_role(Role.ADMIN))]
OwnerOrAnalystDep = Annotated[
    CurrentActor,
    Depends(require_any_role(Role.INFORMATION_OWNER, Role.ANALYST)),
]


@router.get("/information-definitions", response_model=list[DefinitionOut])
async def list_definitions(
    session: SessionDep, actor: ActorDep, active_only: bool = True
) -> list[InformationDefinition]:
    stmt = select(InformationDefinition).order_by(InformationDefinition.information_key)
    if active_only:
        stmt = stmt.where(InformationDefinition.is_active.is_(True))
    return list(await session.scalars(stmt))


@router.post("/information-definitions", response_model=DefinitionOut, status_code=201)
async def create_definition(
    payload: DefinitionCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> InformationDefinition:
    return await InformationRegistryService(session, settings).create_definition(
        actor=actor, **payload.model_dump(exclude_none=True)
    )


@router.post("/information-definitions/{definition_id}/owners", status_code=201)
async def assign_owner(
    definition_id: uuid.UUID,
    payload: OwnerAssignmentCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: ManagerDep,
) -> dict[str, str]:
    assignment = await InformationRegistryService(session, settings).assign_owner(
        definition_id, actor=actor, **payload.model_dump()
    )
    return {"assignment_id": str(assignment.id)}


@router.get("/information-values", response_model=list[InformationValueOut])
async def list_values(
    session: SessionDep,
    actor: ActorDep,
    legal_entity_id: uuid.UUID | None = None,
    definition_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[InformationValue]:
    stmt = select(InformationValue).order_by(InformationValue.created_at.desc())
    if legal_entity_id:
        stmt = stmt.where(InformationValue.legal_entity_id == legal_entity_id)
    if definition_id:
        stmt = stmt.where(InformationValue.information_definition_id == definition_id)
    if status:
        stmt = stmt.where(InformationValue.status == status)
    return list(await session.scalars(stmt))


@router.post("/information-values", response_model=InformationValueOut, status_code=201)
async def create_value(
    payload: ValueCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: OwnerOrAnalystDep,
) -> InformationValue:
    return await InformationRegistryService(session, settings).propose_value(
        actor=actor, **payload.model_dump(exclude_none=True)
    )


@router.get("/information-values/{value_id}", response_model=InformationValueOut)
async def get_value(value_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> InformationValue:
    value = await session.get(InformationValue, value_id)
    if value is None:
        raise NotFoundError("Information value not found.")
    return value


@router.post(
    "/information-values/{value_id}/submit-approval",
    response_model=InformationValueOut,
)
async def submit_value(
    value_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: OwnerOrAnalystDep,
) -> InformationValue:
    return await InformationRegistryService(session, settings).submit_for_approval(
        value_id, actor=actor
    )


@router.post("/information-values/{value_id}/approve", response_model=InformationValueOut)
async def approve_value(
    value_id: uuid.UUID,
    payload: ValueApprove,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> InformationValue:
    return await InformationRegistryService(session, settings).approve_value(
        value_id, actor=actor, cross_entity_approved=payload.cross_entity_approved
    )


@router.post("/information-values/{value_id}/reject", response_model=InformationValueOut)
async def reject_value(
    value_id: uuid.UUID,
    payload: ValueReject,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> InformationValue:
    return await InformationRegistryService(session, settings).reject_value(
        value_id, actor=actor, reason=payload.reason
    )


@router.post("/information-values/{value_id}/supersede", response_model=InformationValueOut)
async def supersede_value(
    value_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> InformationValue:
    return await InformationRegistryService(session, settings).supersede_value(
        value_id, actor=actor
    )


@router.post("/information-values/{value_id}/reveal")
async def reveal_value(
    value_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ManagerDep,
    purpose: str = "MANUAL_LOOKUP",
) -> dict[str, object]:
    plaintext = await InformationRegistryService(session, settings).reveal_value(
        value_id, actor=actor, purpose=purpose
    )
    return {"value_id": str(value_id), "value": plaintext}


@router.post("/information-values/actions/expire-stale")
async def expire_stale(
    session: SessionDep, settings: SettingsDep, actor: ManagerDep
) -> dict[str, int]:
    return await InformationRegistryService(session, settings).expire_stale_values()

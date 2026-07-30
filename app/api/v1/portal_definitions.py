"""Portal registry, terms review, adapters, and operator authorization."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.core.exceptions import NotFoundError
from app.models import (
    PortalAdapterVersion,
    PortalDefinition,
    PortalReviewVersion,
    PortalUserAuthorization,
)
from app.schemas.portal import (
    AdapterCreate,
    AdapterOut,
    AuthorizationOut,
    AuthorizationUpsert,
    FieldMappingCreate,
    PortalCreate,
    PortalOut,
    PortalUpdate,
    ReviewCreate,
    ReviewOut,
)
from app.services.portal_governance_service import PortalGovernanceService

router = APIRouter(tags=["portal-governance"])

AdminDep = Annotated[CurrentActor, Depends(require_role(Role.ADMIN))]
ReviewerDep = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]


@router.get("/portals", response_model=list[PortalOut])
async def list_portals(
    session: SessionDep,
    actor: ActorDep,
    status: str | None = None,
    portal_type: str | None = None,
) -> list[PortalDefinition]:
    stmt = select(PortalDefinition).order_by(PortalDefinition.name)
    if status:
        stmt = stmt.where(PortalDefinition.status == status)
    if portal_type:
        stmt = stmt.where(PortalDefinition.portal_type == portal_type)
    return list(await session.scalars(stmt))


@router.post("/portals", response_model=PortalOut, status_code=201)
async def create_portal(
    payload: PortalCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> PortalDefinition:
    return await PortalGovernanceService(session, settings).create_portal(
        actor=actor, fields=payload.model_dump(exclude_none=True)
    )


@router.get("/portals/{portal_id}", response_model=PortalOut)
async def get_portal(
    portal_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> PortalDefinition:
    portal = await session.get(PortalDefinition, portal_id)
    if portal is None:
        raise NotFoundError("Portal not found.")
    return portal


@router.patch("/portals/{portal_id}", response_model=PortalOut)
async def update_portal(
    portal_id: uuid.UUID,
    payload: PortalUpdate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> PortalDefinition:
    return await PortalGovernanceService(session, settings).update_portal(
        portal_id,
        actor=actor,
        changes=payload.model_dump(exclude_unset=True),
    )


@router.get("/portals/{portal_id}/reviews", response_model=list[ReviewOut])
async def list_reviews(
    portal_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[PortalReviewVersion]:
    return list(
        await session.scalars(
            select(PortalReviewVersion)
            .where(PortalReviewVersion.portal_definition_id == portal_id)
            .order_by(PortalReviewVersion.version.desc())
        )
    )


@router.post("/portals/{portal_id}/reviews", response_model=ReviewOut, status_code=201)
async def create_review(
    portal_id: uuid.UUID,
    payload: ReviewCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> PortalReviewVersion:
    return await PortalGovernanceService(session, settings).create_review(
        portal_id,
        actor=actor,
        fields=payload.model_dump(exclude_none=True),
    )


@router.post("/portal-reviews/{review_id}/approve", response_model=ReviewOut)
async def approve_review(
    review_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> PortalReviewVersion:
    return await PortalGovernanceService(session, settings).approve_review(review_id, actor=actor)


@router.post(
    "/portal-reviews/{review_id}/compliance-signoff",
    response_model=ReviewOut,
)
async def compliance_signoff(
    review_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> PortalReviewVersion:
    return await PortalGovernanceService(session, settings).record_review_signoff(
        review_id, actor=actor, review_domain="compliance"
    )


@router.post(
    "/portal-reviews/{review_id}/security-signoff",
    response_model=ReviewOut,
)
async def security_signoff(
    review_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> PortalReviewVersion:
    return await PortalGovernanceService(session, settings).record_review_signoff(
        review_id, actor=actor, review_domain="security"
    )


@router.post("/portal-reviews/{review_id}/suspend", response_model=ReviewOut)
async def suspend_review(
    review_id: uuid.UUID,
    reason: str,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> PortalReviewVersion:
    return await PortalGovernanceService(session, settings).suspend_review(
        review_id, actor=actor, reason=reason
    )


@router.get("/portals/{portal_id}/adapters", response_model=list[AdapterOut])
async def list_adapters(
    portal_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[PortalAdapterVersion]:
    return list(
        await session.scalars(
            select(PortalAdapterVersion)
            .where(PortalAdapterVersion.portal_definition_id == portal_id)
            .order_by(PortalAdapterVersion.adapter_key, PortalAdapterVersion.version.desc())
        )
    )


@router.post("/portals/{portal_id}/adapters", response_model=AdapterOut, status_code=201)
async def create_adapter(
    portal_id: uuid.UUID,
    payload: AdapterCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> PortalAdapterVersion:
    return await PortalGovernanceService(session, settings).create_adapter(
        portal_id,
        actor=actor,
        fields=payload.model_dump(exclude_none=True),
    )


@router.post("/portals/{portal_id}/adapters/{adapter_id}/activate", response_model=AdapterOut)
async def activate_adapter(
    portal_id: uuid.UUID,
    adapter_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> PortalAdapterVersion:
    adapter = await session.get(PortalAdapterVersion, adapter_id)
    if adapter is None or adapter.portal_definition_id != portal_id:
        raise NotFoundError("Portal adapter not found.")
    return await PortalGovernanceService(session, settings).activate_adapter(
        adapter_id, actor=actor
    )


@router.post("/portal-adapters/{adapter_id}/field-mappings", status_code=201)
async def create_field_mapping(
    adapter_id: uuid.UUID,
    payload: FieldMappingCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> dict[str, str]:
    mapping = await PortalGovernanceService(session, settings).add_field_mapping(
        adapter_id,
        actor=actor,
        fields=payload.model_dump(exclude_none=True),
    )
    return {"id": str(mapping.id), "status": "CREATED"}


@router.get(
    "/portals/{portal_id}/authorizations",
    response_model=list[AuthorizationOut],
)
async def list_authorizations(
    portal_id: uuid.UUID, session: SessionDep, actor: AdminDep
) -> list[PortalUserAuthorization]:
    return list(
        await session.scalars(
            select(PortalUserAuthorization).where(
                PortalUserAuthorization.portal_definition_id == portal_id
            )
        )
    )


@router.post(
    "/portals/{portal_id}/authorizations",
    response_model=AuthorizationOut,
)
async def upsert_authorization(
    portal_id: uuid.UUID,
    payload: AuthorizationUpsert,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> PortalUserAuthorization:
    return await PortalGovernanceService(session, settings).upsert_authorization(
        portal_id,
        actor=actor,
        fields=payload.model_dump(exclude_none=True),
    )

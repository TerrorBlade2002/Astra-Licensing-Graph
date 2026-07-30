"""Compliance obligations, cases, stages, and vendor-question endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_any_role, require_role
from app.auth.roles import Role
from app.core.exceptions import NotFoundError
from app.models import CaseInformationRequest, ComplianceCase, ComplianceObligation
from app.schemas.licensing import (
    CaseCreate,
    CaseOut,
    CaseStageEventOut,
    CaseTransition,
    CaseUpdate,
    InformationRequestCreate,
    InformationRequestOut,
    InformationRequestUpdate,
    ObligationCreate,
    ObligationOut,
    ObligationUpdate,
)
from app.services.compliance_case_service import ComplianceCaseService

router = APIRouter(tags=["compliance-cases"])

AnalystDep = Annotated[CurrentActor, Depends(require_role(Role.ANALYST))]
ReviewerDep = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]
OwnerOrReviewerDep = Annotated[
    CurrentActor,
    Depends(require_any_role(Role.INFORMATION_OWNER, Role.REVIEWER)),
]


@router.get("/compliance-obligations", response_model=list[ObligationOut])
async def list_obligations(
    session: SessionDep,
    actor: ActorDep,
    legal_entity_id: uuid.UUID | None = None,
    status: str | None = None,
    obligation_type: str | None = None,
) -> list[ComplianceObligation]:
    stmt = select(ComplianceObligation).order_by(ComplianceObligation.next_due_date.nulls_last())
    if legal_entity_id:
        stmt = stmt.where(ComplianceObligation.legal_entity_id == legal_entity_id)
    if status:
        stmt = stmt.where(ComplianceObligation.status == status)
    if obligation_type:
        stmt = stmt.where(ComplianceObligation.obligation_type == obligation_type)
    return list(await session.scalars(stmt))


@router.post("/compliance-obligations", response_model=ObligationOut, status_code=201)
async def create_obligation(
    payload: ObligationCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> ComplianceObligation:
    return await ComplianceCaseService(session, settings).create_obligation(
        actor=actor, **payload.model_dump(exclude_none=True)
    )


@router.get("/compliance-obligations/{obligation_id}", response_model=ObligationOut)
async def get_obligation(
    obligation_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> ComplianceObligation:
    obligation = await session.get(ComplianceObligation, obligation_id)
    if obligation is None:
        raise NotFoundError("Obligation not found.")
    return obligation


@router.patch("/compliance-obligations/{obligation_id}", response_model=ObligationOut)
async def update_obligation(
    obligation_id: uuid.UUID,
    payload: ObligationUpdate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> ComplianceObligation:
    return await ComplianceCaseService(session, settings).update_obligation(
        obligation_id,
        actor=actor,
        **payload.model_dump(exclude_unset=True),
    )


@router.post(
    "/compliance-obligations/{obligation_id}/next",
    response_model=ObligationOut | None,
)
async def create_next_obligation(
    obligation_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> ComplianceObligation | None:
    return await ComplianceCaseService(session, settings).create_next_obligation(
        obligation_id, actor=actor
    )


@router.get("/compliance-cases", response_model=list[CaseOut])
async def list_cases(
    session: SessionDep,
    actor: ActorDep,
    legal_entity_id: uuid.UUID | None = None,
    status: str | None = None,
    stage: str | None = None,
    assigned_owner: str | None = None,
) -> list[ComplianceCase]:
    stmt = select(ComplianceCase).order_by(ComplianceCase.updated_at.desc())
    if legal_entity_id:
        stmt = stmt.where(ComplianceCase.legal_entity_id == legal_entity_id)
    if status:
        stmt = stmt.where(ComplianceCase.status == status)
    if stage:
        stmt = stmt.where(ComplianceCase.current_stage == stage)
    if assigned_owner:
        stmt = stmt.where(ComplianceCase.assigned_owner == assigned_owner)
    return list(await session.scalars(stmt))


@router.post("/compliance-cases", response_model=CaseOut, status_code=201)
async def create_case(
    payload: CaseCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> ComplianceCase:
    return await ComplianceCaseService(session, settings).open_case(
        payload.obligation_id,
        actor=actor,
        assigned_owner=payload.assigned_owner,
        priority=payload.priority,
    )


@router.get("/compliance-cases/{case_id}", response_model=CaseOut)
async def get_case(case_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> ComplianceCase:
    case = await session.get(ComplianceCase, case_id)
    if case is None:
        raise NotFoundError("Compliance case not found.")
    return case


@router.patch("/compliance-cases/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: uuid.UUID,
    payload: CaseUpdate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> ComplianceCase:
    return await ComplianceCaseService(session, settings).update_case(
        case_id,
        actor=actor,
        **payload.model_dump(exclude_unset=True),
    )


@router.post("/compliance-cases/{case_id}/transition", response_model=CaseOut)
async def transition_case(
    case_id: uuid.UUID,
    payload: CaseTransition,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> ComplianceCase:
    return await ComplianceCaseService(session, settings).transition(
        case_id, actor=actor, **payload.model_dump(exclude_none=True)
    )


@router.get("/compliance-cases/{case_id}/timeline", response_model=list[CaseStageEventOut])
async def case_timeline(
    case_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> list[dict[str, Any]]:
    return await ComplianceCaseService(session, settings).timeline(case_id)


@router.get("/compliance-cases/{case_id}/available-transitions")
async def available_transitions(
    case_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> dict[str, list[str]]:
    return {
        "transitions": await ComplianceCaseService(session, settings).available_transitions(case_id)
    }


@router.get(
    "/compliance-cases/{case_id}/information-requests",
    response_model=list[InformationRequestOut],
)
async def list_information_requests(
    case_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[CaseInformationRequest]:
    return list(
        await session.scalars(
            select(CaseInformationRequest)
            .where(CaseInformationRequest.compliance_case_id == case_id)
            .order_by(CaseInformationRequest.created_at)
        )
    )


@router.post(
    "/compliance-cases/{case_id}/information-requests",
    response_model=InformationRequestOut,
    status_code=201,
)
async def create_information_request(
    case_id: uuid.UUID,
    payload: InformationRequestCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> CaseInformationRequest:
    return await ComplianceCaseService(session, settings).create_information_request(
        case_id, actor=actor, **payload.model_dump(exclude_none=True)
    )


@router.patch(
    "/case-information-requests/{request_id}",
    response_model=InformationRequestOut,
)
async def update_information_request(
    request_id: uuid.UUID,
    payload: InformationRequestUpdate,
    session: SessionDep,
    settings: SettingsDep,
    actor: OwnerOrReviewerDep,
) -> CaseInformationRequest:
    return await ComplianceCaseService(session, settings).update_information_request(
        request_id, actor=actor, **payload.model_dump(exclude_none=True)
    )


@router.post(
    "/case-information-requests/{request_id}/approve-answer",
    response_model=InformationRequestOut,
)
async def approve_answer(
    request_id: uuid.UUID,
    response_value_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> CaseInformationRequest:
    return await ComplianceCaseService(session, settings).update_information_request(
        request_id,
        actor=actor,
        status="ANSWER_APPROVED",
        response_value_id=response_value_id,
    )

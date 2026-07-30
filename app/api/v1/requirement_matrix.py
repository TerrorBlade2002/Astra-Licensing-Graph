"""Advisory licensing-requirement assessment endpoints."""

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
from app.licensing.jobs import LicensingJobType
from app.models import RequirementAssessment, RequirementAssessmentResult
from app.repositories.licensing_jobs import LicensingJobRepository
from app.schemas.licensing import (
    AssessmentCreate,
    AssessmentDetailOut,
    AssessmentOut,
    AssessmentResultOut,
    CounselReviewRequest,
    ResultOverride,
    ResultReview,
)
from app.services.requirement_assessment_service import RequirementAssessmentService

router = APIRouter(tags=["requirement-matrix"])

AnalystDep = Annotated[CurrentActor, Depends(require_role(Role.ANALYST))]
ReviewerDep = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]
ManagerDep = Annotated[CurrentActor, Depends(require_role(Role.MANAGER))]
CounselDep = Annotated[CurrentActor, Depends(require_role(Role.COUNSEL))]


@router.post("/requirement-assessments", response_model=AssessmentOut, status_code=201)
async def create_assessment(
    payload: AssessmentCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> RequirementAssessment:
    return await RequirementAssessmentService(session, settings).create_assessment(
        actor=actor, **payload.model_dump(exclude_none=True)
    )


@router.get("/requirement-assessments", response_model=list[AssessmentOut])
async def list_assessments(
    session: SessionDep, actor: ActorDep, status: str | None = None
) -> list[RequirementAssessment]:
    stmt = select(RequirementAssessment).order_by(RequirementAssessment.created_at.desc())
    if status:
        stmt = stmt.where(RequirementAssessment.status == status)
    return list(await session.scalars(stmt))


async def _detail(session: SessionDep, assessment_id: uuid.UUID) -> AssessmentDetailOut:
    assessment = await session.get(RequirementAssessment, assessment_id)
    if assessment is None:
        raise NotFoundError("Assessment not found.")
    results = list(
        await session.scalars(
            select(RequirementAssessmentResult)
            .where(RequirementAssessmentResult.assessment_id == assessment_id)
            .order_by(RequirementAssessmentResult.jurisdiction_id)
        )
    )
    return AssessmentDetailOut(
        assessment=AssessmentOut.model_validate(assessment),
        results=[AssessmentResultOut.model_validate(result) for result in results],
    )


@router.get("/requirement-assessments/{assessment_id}", response_model=AssessmentDetailOut)
async def get_assessment(
    assessment_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> AssessmentDetailOut:
    return await _detail(session, assessment_id)


@router.post(
    "/requirement-assessments/{assessment_id}/evaluate",
    status_code=202,
)
async def evaluate_assessment(
    assessment_id: uuid.UUID,
    session: SessionDep,
    actor: AnalystDep,
) -> dict[str, object]:
    assessment = await session.get(RequirementAssessment, assessment_id)
    if assessment is None:
        raise NotFoundError("Assessment not found.")
    job, created = await LicensingJobRepository(session).enqueue(
        job_type=LicensingJobType.EVALUATE_REQUIREMENT_ASSESSMENT,
        idempotency_key=(f"evaluate-assessment:{assessment.id}:{assessment.input_fingerprint}"),
        payload={
            "assessment_id": str(assessment.id),
            "requested_by_actor": actor.actor_id,
        },
        legal_entity_id=assessment.legal_entity_id,
    )
    await session.commit()
    return {"job_id": str(job.id), "created": created, "status": job.status}


@router.post("/requirement-results/{result_id}/review", response_model=AssessmentResultOut)
async def review_result(
    result_id: uuid.UUID,
    payload: ResultReview,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> RequirementAssessmentResult:
    return await RequirementAssessmentService(session, settings).review_result(
        result_id, actor=actor, **payload.model_dump()
    )


@router.post("/requirement-assessments/{assessment_id}/approve", response_model=AssessmentOut)
async def approve_assessment(
    assessment_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
    notes: str | None = None,
) -> RequirementAssessment:
    return await RequirementAssessmentService(session, settings).approve(
        assessment_id, actor=actor, notes=notes
    )


@router.post("/requirement-results/{result_id}/override")
async def override_result(
    result_id: uuid.UUID,
    payload: ResultOverride,
    session: SessionDep,
    settings: SettingsDep,
    actor: ManagerDep,
) -> dict[str, str]:
    record = await RequirementAssessmentService(session, settings).override_result(
        result_id, actor=actor, **payload.model_dump(exclude_none=True)
    )
    return {"override_id": str(record.id), "overridden_outcome": record.overridden_outcome}


@router.post(
    "/requirement-results/{result_id}/request-counsel-review",
    response_model=AssessmentResultOut,
)
async def request_counsel_review(
    result_id: uuid.UUID,
    payload: CounselReviewRequest,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> RequirementAssessmentResult:
    return await RequirementAssessmentService(session, settings).request_counsel_review(
        result_id, actor=actor, reason=payload.reason
    )


@router.post(
    "/requirement-results/{result_id}/counsel-review",
    response_model=AssessmentResultOut,
)
async def counsel_review(
    result_id: uuid.UUID,
    payload: ResultReview,
    session: SessionDep,
    settings: SettingsDep,
    actor: CounselDep,
) -> RequirementAssessmentResult:
    return await RequirementAssessmentService(session, settings).review_result(
        result_id, actor=actor, counsel_decision=True, **payload.model_dump()
    )

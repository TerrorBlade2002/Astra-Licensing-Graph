"""Human review queue, evidence detail, decisions, history, and manual enqueue."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.classification.schema import ClassificationOutputV1
from app.jobs.service import GraphJobService
from app.models import Classification, ClassificationReview, Email
from app.reviews.service import ReviewService
from app.schemas.milestone4 import (
    ReviewCorrectionMutation,
    ReviewDetail,
    ReviewMutation,
    ReviewOut,
    ReviewQueueItem,
    ReviewReasonMutation,
    TaskCreateMutation,
)
from app.tasks.creation import TaskCreationService

router = APIRouter(tags=["classification reviews"])
Reviewer = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]


def _output(row: Classification) -> ClassificationOutputV1:
    return ClassificationOutputV1.model_validate(
        {
            key: getattr(row, key)
            for key in (
                "vendor",
                "email_type",
                "states",
                "license_types",
                "license_numbers",
                "action_required",
                "requested_information",
                "documents",
                "due_date",
                "summary",
                "proposed_action",
                "suggested_destination",
                "confidence",
                "requires_human_review",
            )
        }
        | {"review_reasons": row.evidence.get("review_reasons", [])}
    )


@router.get("/classification-reviews", response_model=list[ReviewQueueItem])
async def queue(
    session: SessionDep,
    actor: ActorDep,
    status: str | None = None,
    vendor: str | None = None,
    email_type: str | None = None,
    state: str | None = None,
    confidence_min: float | None = None,
    confidence_max: float | None = None,
    claimed_by: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> list[ReviewQueueItem]:
    stmt = (
        select(ClassificationReview, Classification, Email)
        .select_from(ClassificationReview)
        .join(Classification, ClassificationReview.classification_id == Classification.id)
        .join(Email, Classification.email_id == Email.id)
        .where(Classification.is_current.is_(True))
    )
    if status:
        stmt = stmt.where(ClassificationReview.decision == status)
    if vendor:
        stmt = stmt.where(Classification.vendor == vendor)
    if email_type:
        stmt = stmt.where(Classification.email_type == email_type)
    if state:
        stmt = stmt.where(Classification.states.contains([state]))
    if confidence_min is not None:
        stmt = stmt.where(Classification.confidence >= confidence_min)
    if confidence_max is not None:
        stmt = stmt.where(Classification.confidence <= confidence_max)
    if claimed_by:
        stmt = stmt.where(ClassificationReview.reviewer_principal == claimed_by)
    rows = (
        await session.execute(
            stmt.order_by(Email.received_at.desc().nulls_last())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [
        ReviewQueueItem(
            review=ReviewOut.model_validate(r),
            classification=_output(c),
            classification_version=c.version,
            email_id=e.id,
            received_at=e.received_at,
            sender=e.sender_email,
            subject=e.subject,
            has_attachments=e.has_attachments,
        )
        for r, c, e in rows
    ]


@router.get("/classification-reviews/{classification_id}", response_model=ReviewDetail)
async def detail(
    classification_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> ReviewDetail:
    row = (
        await session.execute(
            select(ClassificationReview, Classification, Email)
            .select_from(ClassificationReview)
            .join(Classification, ClassificationReview.classification_id == Classification.id)
            .join(Email, Classification.email_id == Email.id)
            .where(Classification.id == classification_id)
        )
    ).first()
    if not row:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Classification review does not exist.")
    review, classification, email = row
    versions = list(
        await session.scalars(
            select(Classification.version)
            .where(Classification.email_id == email.id)
            .order_by(Classification.version.desc())
        )
    )
    evidence = classification.evidence or {}
    return ReviewDetail(
        review=ReviewOut.model_validate(review),
        classification=_output(classification),
        classification_version=classification.version,
        email_id=email.id,
        received_at=email.received_at,
        sender=email.sender_email,
        subject=email.subject,
        has_attachments=email.has_attachments,
        current_message_body=str(evidence.get("current_message", email.body_text or "")),
        quoted_history=str(evidence.get("quoted_history", "")),
        rule_evidence=classification.rule_matches,
        previous_versions=versions,
    )


@router.post("/classification-reviews/{classification_id}/claim", response_model=ReviewOut)
async def claim(
    classification_id: uuid.UUID,
    body: ReviewMutation,
    session: SessionDep,
    settings: SettingsDep,
    actor: Reviewer,
) -> ReviewOut:
    return ReviewOut.model_validate(
        await ReviewService(session, settings).claim(
            classification_id, actor, body.expected_revision
        )
    )


@router.post("/classification-reviews/{classification_id}/release", response_model=ReviewOut)
async def release(
    classification_id: uuid.UUID,
    body: ReviewMutation,
    session: SessionDep,
    settings: SettingsDep,
    actor: Reviewer,
) -> ReviewOut:
    return ReviewOut.model_validate(
        await ReviewService(session, settings).release(
            classification_id, actor, body.expected_revision
        )
    )


@router.post("/classification-reviews/{classification_id}/approve", response_model=ReviewOut)
async def approve(
    classification_id: uuid.UUID,
    body: ReviewMutation,
    session: SessionDep,
    settings: SettingsDep,
    actor: Reviewer,
) -> ReviewOut:
    return ReviewOut.model_validate(
        await ReviewService(session, settings).decide(
            classification_id, actor, body.expected_revision, "APPROVED"
        )
    )


@router.post("/classification-reviews/{classification_id}/correct", response_model=ReviewOut)
async def correct(
    classification_id: uuid.UUID,
    body: ReviewCorrectionMutation,
    session: SessionDep,
    settings: SettingsDep,
    actor: Reviewer,
) -> ReviewOut:
    return ReviewOut.model_validate(
        await ReviewService(session, settings).decide(
            classification_id,
            actor,
            body.expected_revision,
            "CORRECTED",
            corrected=body.classification,
            correction_reasons=body.correction_reasons,
            reason=body.notes,
        )
    )


@router.post("/classification-reviews/{classification_id}/reject", response_model=ReviewOut)
async def reject(
    classification_id: uuid.UUID,
    body: ReviewReasonMutation,
    session: SessionDep,
    settings: SettingsDep,
    actor: Reviewer,
) -> ReviewOut:
    return ReviewOut.model_validate(
        await ReviewService(session, settings).decide(
            classification_id, actor, body.expected_revision, "REJECTED", reason=body.reason
        )
    )


@router.post(
    "/classification-reviews/{classification_id}/request-reclassification", response_model=ReviewOut
)
async def request_reclassification(
    classification_id: uuid.UUID,
    body: ReviewReasonMutation,
    session: SessionDep,
    settings: SettingsDep,
    actor: Reviewer,
) -> ReviewOut:
    return ReviewOut.model_validate(
        await ReviewService(session, settings).decide(
            classification_id,
            actor,
            body.expected_revision,
            "RECLASSIFICATION_REQUESTED",
            reason=body.reason,
        )
    )


@router.get("/emails/{email_id}/classifications")
async def history(
    email_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[dict[str, object]]:
    rows = list(
        await session.scalars(
            select(Classification)
            .where(Classification.email_id == email_id)
            .order_by(Classification.version.desc())
        )
    )
    return [
        {
            "id": str(row.id),
            "version": row.version,
            "is_current": row.is_current,
            "review_status": row.review_status,
            "classification": _output(row).model_dump(mode="json"),
        }
        for row in rows
    ]


@router.post("/emails/{email_id}/classification-jobs", status_code=202)
async def enqueue(
    email_id: uuid.UUID, session: SessionDep, settings: SettingsDep, actor: Reviewer
) -> dict[str, object]:
    email = await session.get(Email, email_id)
    if email is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Email does not exist.")
    result = await GraphJobService(session, settings).enqueue_classify_email(
        mailbox_id=email.mailbox_id,
        email_id=email.id,
        reason="manual portal request",
        reclassification=email.processing_state == "CLASSIFIED",
    )
    await session.commit()
    return {"job_id": str(result.job.id), "created": result.created}


@router.post("/classification-reviews/{review_id}/create-task", status_code=201)
async def create_task(
    review_id: uuid.UUID, body: TaskCreateMutation, session: SessionDep, actor: Reviewer
) -> dict[str, object]:
    task = await TaskCreationService(session).create(
        review_id,
        actor,
        destination_override=body.destination_override,
        override_reason=body.override_reason,
    )
    return {"id": str(task.id), "title": task.title, "queue": task.queue, "status": task.status}

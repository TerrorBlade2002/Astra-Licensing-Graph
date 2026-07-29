"""Claim leases, optimistic review decisions, corrections, and reclassification requests."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, cast

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.classification.schema import ClassificationOutputV1
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.jobs.service import GraphJobService
from app.models import (
    AuditEvent,
    Classification,
    ClassificationFieldCorrection,
    ClassificationReview,
    Email,
)
from app.models.mixins import utcnow


class ReviewService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings

    async def claim(
        self, classification_id: uuid.UUID, actor: CurrentActor, expected_revision: int
    ) -> ClassificationReview:
        review = await self._locked(classification_id)
        self._revision(review, expected_revision)
        now = utcnow()
        if (
            review.reviewer_principal
            and review.reviewer_principal != actor.actor_id
            and review.claim_expires_at
            and review.claim_expires_at > now
        ):
            raise StateConflictError(
                "Review is claimed by another reviewer.",
                details={"revision": review.revision, "claimed_by": review.reviewer_principal},
            )
        review.reviewer_principal, review.claimed_at = actor.actor_id, now
        review.claim_expires_at = now + timedelta(minutes=self.settings.review_claim_lease_minutes)
        review.decision, review.revision = "IN_REVIEW", review.revision + 1
        await self.session.commit()
        return review

    async def release(
        self, classification_id: uuid.UUID, actor: CurrentActor, expected_revision: int
    ) -> ClassificationReview:
        review = await self._locked(classification_id)
        self._revision(review, expected_revision)
        if review.reviewer_principal not in (None, actor.actor_id):
            raise StateConflictError("Only the claimant can release this review.")
        review.reviewer_principal = None
        review.claimed_at = None
        review.claim_expires_at = None
        review.decision = "PENDING"
        review.revision += 1
        await self.session.commit()
        return review

    async def decide(
        self,
        classification_id: uuid.UUID,
        actor: CurrentActor,
        expected_revision: int,
        decision: str,
        *,
        reason: str | None = None,
        corrected: ClassificationOutputV1 | None = None,
        correction_reasons: dict[str, str] | None = None,
    ) -> ClassificationReview:
        review = await self._locked(classification_id)
        self._revision(review, expected_revision)
        if review.reviewer_principal not in (None, actor.actor_id):
            raise StateConflictError("Review is claimed by another reviewer.")
        if decision == "CORRECTED" and (
            corrected is None
            or (self.settings.review_require_correction_reason and not correction_reasons)
        ):
            raise ValueError("Corrected reviews require corrected data and correction reasons.")
        if decision in {"REJECTED", "RECLASSIFICATION_REQUESTED"} and not reason:
            raise ValueError("This review decision requires a reason.")
        classification = await self.session.get(Classification, classification_id)
        if classification is None:
            raise NotFoundError("Classification does not exist.")
        now = utcnow()
        review.decision = decision
        review.reviewer_principal = actor.actor_id
        review.reviewed_at = now
        review.review_notes = reason
        review.rejection_reason = reason if decision == "REJECTED" else None
        review.reclassification_reason = (
            reason if decision == "RECLASSIFICATION_REQUESTED" else None
        )
        review.corrected_classification = corrected.model_dump(mode="json") if corrected else None
        review.revision += 1
        classification.review_status = decision
        classification.reviewed_at = now
        classification.reviewed_by_actor = actor.actor_id
        classification.rejection_reason = review.rejection_reason
        if corrected:
            machine = self._machine(classification)
            reviewed = corrected.model_dump(mode="json")
            for path, correction_reason in (correction_reasons or {}).items():
                self.session.add(
                    ClassificationFieldCorrection(
                        review_id=review.id,
                        field_path=path,
                        machine_value=machine.get(path),
                        reviewed_value=reviewed.get(path),
                        correction_reason=correction_reason,
                    )
                )
        self.session.add(
            AuditEvent(
                actor_type="HUMAN",
                actor_id=actor.actor_id,
                entity_type="classification_review",
                entity_id=str(review.id),
                action=f"review:{decision.lower()}",
                before_data={"revision": expected_revision},
                after_data={"decision": decision, "revision": review.revision},
                event_metadata={"reason": reason},
                occurred_at=now,
            )
        )
        if decision == "RECLASSIFICATION_REQUESTED":
            email = await self.session.get(Email, classification.email_id)
            if email:
                await GraphJobService(self.session, self.settings).enqueue_classify_email(
                    mailbox_id=email.mailbox_id,
                    email_id=email.id,
                    reason=reason or "reviewer request",
                    reclassification=True,
                )
        await self.session.commit()
        return review

    async def _locked(self, classification_id: uuid.UUID) -> ClassificationReview:
        review = (
            await self.session.scalars(
                select(ClassificationReview)
                .where(ClassificationReview.classification_id == classification_id)
                .order_by(ClassificationReview.created_at.desc())
                .with_for_update()
            )
        ).first()
        if review is None:
            raise NotFoundError("Classification review does not exist.")
        return review

    @staticmethod
    def _revision(review: ClassificationReview, expected: int) -> None:
        if review.revision != expected:
            raise StateConflictError(
                "Review was updated by another user.",
                details={
                    "expected_revision": expected,
                    "current_revision": review.revision,
                    "decision": review.decision,
                },
            )

    @staticmethod
    def _machine(row: Classification) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            jsonable_encoder(
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
            ),
        )

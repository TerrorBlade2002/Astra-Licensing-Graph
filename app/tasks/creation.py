"""Atomic, idempotent task creation from an approved human review."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.classification.schema import ClassificationOutputV1
from app.core.exceptions import NotFoundError, StateConflictError
from app.domain.enums import ProcessingState
from app.models import (
    AuditEvent,
    Classification,
    ClassificationReview,
    Email,
    LicensingTask,
    MailboxFolder,
    OutboxEvent,
    TaskEvent,
    TaskRequestedItem,
)
from app.models.mixins import utcnow
from app.services.email_state import Actor, _transition_locked


class TaskCreationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        review_id: uuid.UUID,
        actor: CurrentActor,
        *,
        destination_override: str | None = None,
        override_reason: str | None = None,
    ) -> LicensingTask:
        async with self.session.begin():
            review = (
                await self.session.scalars(
                    select(ClassificationReview)
                    .where(ClassificationReview.id == review_id)
                    .with_for_update()
                )
            ).first()
            if review is None:
                raise NotFoundError("Review does not exist.")
            existing = (
                await self.session.scalars(
                    select(LicensingTask).where(
                        LicensingTask.task_key == f"review:{review.id}:primary"
                    )
                )
            ).first()
            if existing:
                return existing
            if review.decision not in {"APPROVED", "CORRECTED"}:
                raise StateConflictError("Task creation requires an approved or corrected review.")
            classification = (
                await self.session.scalars(
                    select(Classification)
                    .where(Classification.id == review.classification_id)
                    .with_for_update()
                )
            ).first()
            if classification is None:
                raise NotFoundError("Classification does not exist.")
            email = (
                await self.session.scalars(
                    select(Email).where(Email.id == classification.email_id).with_for_update()
                )
            ).first()
            if email is None:
                raise NotFoundError("Source email does not exist.")
            if email.processing_state != ProcessingState.CLASSIFIED.value:
                raise StateConflictError("Source email is not CLASSIFIED.")
            output = ClassificationOutputV1.model_validate(
                review.corrected_classification or self._classification_data(classification)
            )
            destination = destination_override or output.suggested_destination
            if destination_override and not override_reason:
                raise ValueError("A routing override requires a reason.")
            destination_folder = await self.session.scalar(
                select(MailboxFolder).where(
                    MailboxFolder.mailbox_id == email.mailbox_id,
                    MailboxFolder.display_name == destination,
                )
            )
            title = self._title(output)
            now = utcnow()
            task = LicensingTask(
                task_key=f"review:{review.id}:primary",
                email_id=email.id,
                classification_id=classification.id,
                review_id=review.id,
                title=title,
                queue=destination,
                status="OPEN",
                destination_folder_name=destination,
                destination_folder_id=(
                    destination_folder.graph_folder_id if destination_folder else None
                ),
                due_date=output.due_date,
                vendor=output.vendor,
                email_type=output.email_type,
                proposed_action=output.proposed_action,
                draft_required=False,
                draft_status="NOT_REQUIRED",
                priority="NORMAL",
            )
            self.session.add(task)
            await self.session.flush()
            for index, item in enumerate(output.requested_information):
                self.session.add(
                    TaskRequestedItem(
                        task_id=task.id,
                        item_text=item.item,
                        category=item.category,
                        required=item.required,
                        evidence_quote=item.evidence_quote,
                        status="OPEN",
                        sort_order=index,
                    )
                )
            self.session.add(
                TaskEvent(
                    task_id=task.id,
                    event_type="CREATED",
                    to_status="OPEN",
                    actor_id=actor.actor_id,
                    event_metadata={
                        "review_id": str(review.id),
                        "destination": destination,
                        "override_reason": override_reason,
                    },
                    occurred_at=now,
                )
            )
            self.session.add(
                AuditEvent(
                    actor_type="HUMAN",
                    actor_id=actor.actor_id,
                    entity_type="licensing_task",
                    entity_id=str(task.id),
                    action="task_created",
                    after_data={"title": title, "queue": destination},
                    event_metadata={
                        "review_id": str(review.id),
                        "override_reason": override_reason,
                    },
                    occurred_at=now,
                )
            )
            self.session.add(
                OutboxEvent(
                    aggregate_type="licensing_task",
                    aggregate_id=str(task.id),
                    event_type="licensing_task.created",
                    payload={
                        "task_id": str(task.id),
                        "email_id": str(email.id),
                        "classification_id": str(classification.id),
                    },
                    idempotency_key=f"task-created:{review.id}",
                    status="PENDING",
                    available_at=now,
                )
            )
            await _transition_locked(
                self.session,
                email.id,
                ProcessingState.TASK_CREATED,
                Actor(actor.actor_type, actor.actor_id),
                "Approved classification converted to licensing task.",
                error_code=None,
                error_message=None,
                metadata={"task_id": str(task.id), "review_id": str(review.id)},
                expected_current_state=ProcessingState.CLASSIFIED,
                manual_reset=False,
                event_type="task_created",
            )
        return task

    @staticmethod
    def _classification_data(row: Classification) -> dict[str, object]:
        reasons = row.evidence.get("review_reasons", ["Initial rollout requires review."])
        return {
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
        } | {"review_reasons": reasons}

    @staticmethod
    def _title(output: ClassificationOutputV1) -> str:
        parts = [
            (output.states or ["Unspecified jurisdiction"])[0],
            (output.license_types or ["Licensing"])[0],
            output.email_type.replace("_", " ").title(),
        ]
        return " - ".join(parts)

"""Atomic email routing completion that never auto-completes the licensing task."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.communications.enums import MoveAttemptStatus, ResponseType
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import COMMUNICATION_WORKFLOWS_COMPLETED_TOTAL
from app.domain.enums import ProcessingState
from app.models import (
    AuditEvent,
    Email,
    LicensingTask,
    MessageMoveAttempt,
    OutboundDraft,
    OutboundSendAttempt,
    OutboxEvent,
    ResponsePlan,
    WorkflowCompletionRecord,
)
from app.models.mixins import utcnow
from app.services.email_state import _transition_locked


class WorkflowCompletionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def complete(self, email_id: uuid.UUID, actor: CurrentActor) -> WorkflowCompletionRecord:
        existing: WorkflowCompletionRecord | None = await self.session.scalar(
            select(WorkflowCompletionRecord).where(WorkflowCompletionRecord.email_id == email_id)
        )
        if existing:
            return existing
        email = await self.session.scalar(
            select(Email).where(Email.id == email_id).with_for_update()
        )
        existing = await self.session.scalar(
            select(WorkflowCompletionRecord).where(WorkflowCompletionRecord.email_id == email_id)
        )
        if existing:
            return existing
        task = await self.session.scalar(
            select(LicensingTask).where(LicensingTask.email_id == email_id).with_for_update()
        )
        plan = await self.session.scalar(
            select(ResponsePlan).where(ResponsePlan.email_id == email_id).with_for_update()
        )
        move = await self.session.scalar(
            select(MessageMoveAttempt)
            .where(
                MessageMoveAttempt.email_id == email_id,
                MessageMoveAttempt.status == MoveAttemptStatus.VERIFIED,
            )
            .order_by(MessageMoveAttempt.attempt_number.desc())
            .with_for_update()
        )
        if email is None or task is None or plan is None or move is None:
            raise NotFoundError("Verified routing prerequisites are missing.")
        if email.processing_state != ProcessingState.TASK_CREATED:
            raise StateConflictError("Email workflow is not at TASK_CREATED.")
        draft = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.response_plan_id == plan.id).with_for_update()
        )
        send_attempt = None
        if plan.response_type != ResponseType.NO_RESPONSE_REQUIRED:
            if draft is None:
                raise StateConflictError("Response-required workflow has no draft.")
            send_attempt = await self.session.scalar(
                select(OutboundSendAttempt)
                .where(OutboundSendAttempt.outbound_draft_id == draft.id)
                .order_by(OutboundSendAttempt.attempt_number.desc())
                .with_for_update()
            )
            if send_attempt is None or send_attempt.status != "SENT_COPY_VERIFIED":
                raise StateConflictError("Sent copy has not been verified.")
        now = utcnow()
        await _transition_locked(
            self.session,
            email.id,
            ProcessingState.MOVED,
            actor,
            "Source message move verified.",
            metadata={"move_attempt_id": str(move.id)},
            expected_current_state=ProcessingState.TASK_CREATED,
            error_code=None,
            error_message=None,
            manual_reset=False,
            event_type="communication_workflow_completion",
        )
        email.graph_message_id = move.returned_graph_message_id or email.graph_message_id
        email.current_graph_folder_id = move.destination_folder_id
        await _transition_locked(
            self.session,
            email.id,
            ProcessingState.COMPLETED,
            actor,
            "Email intake and routing workflow completed.",
            metadata={"move_attempt_id": str(move.id)},
            expected_current_state=ProcessingState.MOVED,
            error_code=None,
            error_message=None,
            manual_reset=False,
            event_type="communication_workflow_completion",
        )
        completion_type = (
            "NO_RESPONSE_REQUIRED_AND_ROUTED"
            if plan.response_type == ResponseType.NO_RESPONSE_REQUIRED
            else "ACKNOWLEDGEMENT_SENT_AND_ROUTED"
            if plan.response_type == ResponseType.ACKNOWLEDGEMENT
            else "RESPONSE_SENT_AND_ROUTED"
        )
        record = WorkflowCompletionRecord(
            email_id=email.id,
            task_id=task.id,
            response_plan_id=plan.id,
            outbound_draft_id=draft.id if draft else None,
            send_attempt_id=send_attempt.id if send_attempt else None,
            move_attempt_id=move.id,
            completion_type=completion_type,
            destination_folder_id=move.destination_folder_id,
            destination_folder_name=move.destination_folder_name,
            final_graph_message_id=move.returned_graph_message_id or email.graph_message_id,
            communication_status="COMPLETED",
            task_status_at_completion=task.status,
            completed_by_actor=actor.actor_id,
            completed_at=now,
            completion_metadata={
                "delivery_status": draft.delivery_status if draft else "NOT_APPLICABLE"
            },
        )
        task.communication_status = "COMPLETED"
        # Deliberately do not mutate task.status or task.completed_at.
        self.session.add(record)
        self.session.add(
            AuditEvent(
                actor_type=actor.actor_type.value,
                actor_id=actor.actor_id,
                entity_type="workflow_completion",
                entity_id=str(record.id),
                action="email_workflow_completed",
                before_data={"email_state": "TASK_CREATED", "task_status": task.status},
                after_data={"email_state": "COMPLETED", "task_status": task.status},
                event_metadata={"move_attempt_id": str(move.id)},
                occurred_at=now,
            )
        )
        self.session.add(
            OutboxEvent(
                aggregate_type="email",
                aggregate_id=str(email.id),
                event_type="email.communication_completed",
                payload={"email_id": str(email.id), "task_id": str(task.id)},
                idempotency_key=f"communication-complete:{email.id}",
                status="PENDING",
                available_at=now,
            )
        )
        await self.session.commit()
        COMMUNICATION_WORKFLOWS_COMPLETED_TOTAL.inc()
        return record

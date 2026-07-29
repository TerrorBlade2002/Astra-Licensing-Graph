"""Response-plan creation keeps communication approval separate from classification review."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.communications.audit import add_communication_audit
from app.communications.enums import ReadinessStatus, RecipientMode, ResponseType
from app.communications.readiness import ResponseReadinessService
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import COMMUNICATION_RESPONSE_PLANS_TOTAL
from app.models import (
    LicensingTask,
    ResponsePlan,
    ResponseTemplate,
    ResponseTemplateVersion,
    TaskRequestedItem,
)


class ResponsePlanService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        task_id: uuid.UUID,
        *,
        response_type: str,
        recipient_mode: str,
        template_version_id: uuid.UUID | None,
        actor: CurrentActor,
        commit: bool = True,
    ) -> ResponsePlan:
        task = await self.session.get(LicensingTask, task_id)
        if task is None or task.email_id is None or task.classification_id is None:
            raise NotFoundError("Task is not linked to reviewed email evidence.")
        try:
            parsed_response_type = ResponseType(response_type)
            parsed_recipient_mode = RecipientMode(recipient_mode)
        except ValueError:
            raise StateConflictError("Response type or recipient mode is invalid.") from None
        existing = await self.session.scalar(
            select(ResponsePlan).where(ResponsePlan.task_id == task_id)
        )
        if existing:
            raise StateConflictError("A response plan already exists for this task.")
        required = parsed_response_type != ResponseType.NO_RESPONSE_REQUIRED
        if not required and parsed_recipient_mode != RecipientMode.NONE:
            raise ValueError("No-response plans must use recipient mode NONE.")
        if required and parsed_recipient_mode == RecipientMode.NONE:
            raise StateConflictError("A response-required plan must have a recipient mode.")
        if required:
            version = (
                await self.session.get(ResponseTemplateVersion, template_version_id)
                if template_version_id
                else None
            )
            template = (
                await self.session.get(ResponseTemplate, version.response_template_id)
                if version
                else None
            )
            if (
                version is None
                or version.status != "ACTIVE"
                or template is None
                or not template.is_active
                or template.response_type != parsed_response_type
            ):
                raise StateConflictError(
                    "The response plan requires an active matching template version."
                )
        elif template_version_id is not None:
            raise StateConflictError("A no-response plan cannot select a response template.")
        requested_statuses = list(
            await self.session.scalars(
                select(TaskRequestedItem.status).where(TaskRequestedItem.task_id == task.id)
            )
        )
        readiness = ResponseReadinessService().evaluate(
            response_type=parsed_response_type,
            requested_item_statuses=requested_statuses,
            recipient_count=0 if parsed_recipient_mode == RecipientMode.NONE else 1,
            task_status=task.status,
            task_owner=task.assigned_to,
            destination_folder_id=task.destination_folder_id,
            response_deadline=task.due_date,
            check_task_context=True,
        )
        if not required and readiness.status != ReadinessStatus.NOT_REQUIRED:
            raise StateConflictError(
                "No-response routing is not ready.",
                details={"blockers": list(readiness.blockers)},
            )
        plan = ResponsePlan(
            task_id=task.id,
            email_id=task.email_id,
            classification_id=task.classification_id,
            response_type=parsed_response_type,
            response_required=required,
            readiness_status=readiness.status,
            readiness_blockers=list(readiness.blockers),
            selected_template_version_id=template_version_id,
            selected_signature_key="licensing-standard",
            suggested_subject=None,
            suggested_destination_folder_name=task.destination_folder_name,
            proposed_recipient_mode=parsed_recipient_mode,
            created_by_actor=actor.actor_id,
            reviewed_by_actor=actor.actor_id if not required else None,
        )
        task.communication_status = "PLAN_CREATED"
        self.session.add(plan)
        await self.session.flush()
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="response_plan",
            entity_id=plan.id,
            action="response_plan_created",
            after={"response_type": plan.response_type, "response_required": required},
        )
        if commit:
            await self.session.commit()
        COMMUNICATION_RESPONSE_PLANS_TOTAL.inc()
        return plan

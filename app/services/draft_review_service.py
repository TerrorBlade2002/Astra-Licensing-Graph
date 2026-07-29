"""Draft-content review remains distinct from send approval."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.communications.attachments import validate_draft_attachments
from app.communications.audit import add_communication_audit
from app.communications.enums import CommunicationDraftStatus, ReadinessStatus, ResponseType
from app.communications.readiness import ResponseReadinessService
from app.communications.recipients import RecipientPolicyService
from app.communications.snapshots import invalidate_approval
from app.communications.validation import validate_draft_content
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import (
    COMMUNICATION_DRAFT_VALIDATION_FAILURES_TOTAL,
    COMMUNICATION_RECIPIENT_POLICY_BLOCKS_TOTAL,
)
from app.models import (
    LicensingTask,
    OutboundDraft,
    OutboundDraftAttachment,
    RecipientPolicyRule,
    ResponsePlan,
    TaskEvent,
    TaskRequestedItem,
)
from app.models.mixins import utcnow


class DraftReviewService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings

    async def submit(
        self,
        draft_id: uuid.UUID,
        actor: CurrentActor,
        *,
        expected_revision: int,
        expected_graph_change_key: str | None,
        expected_graph_etag: str | None,
    ) -> OutboundDraft:
        draft = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.id == draft_id).with_for_update()
        )
        if draft is None or draft.response_plan_id is None:
            raise NotFoundError("Draft does not exist.")
        self._assert_expected(
            draft,
            expected_revision,
            expected_graph_change_key,
            expected_graph_etag,
        )
        plan = await self.session.get(ResponsePlan, draft.response_plan_id)
        if plan is None or not draft.graph_draft_message_id:
            raise StateConflictError("A synchronized Graph draft is required.")
        task = await self.session.get(LicensingTask, draft.task_id)
        if task is None:
            raise NotFoundError("Licensing task does not exist.")
        attachment_count = int(
            await self.session.scalar(
                select(func.count(OutboundDraftAttachment.id)).where(
                    OutboundDraftAttachment.outbound_draft_id == draft.id,
                    OutboundDraftAttachment.removed_at.is_(None),
                )
            )
            or 0
        )
        findings = validate_draft_content(
            subject=draft.subject,
            body_text=draft.body_text,
            body_html=draft.body_html,
            attachment_count=attachment_count,
        )
        if len((draft.body_text or "") + (draft.body_html or "")) > (
            self.settings.communication_max_body_chars
        ):
            findings.append("BODY_TOO_LARGE")
        policy_rules = list(
            await self.session.scalars(
                select(RecipientPolicyRule).where(RecipientPolicyRule.enabled.is_(True))
            )
        )
        recipient_result = RecipientPolicyService(self.settings).evaluate(
            mode=plan.proposed_recipient_mode,
            to_recipients=draft.to_recipients,
            cc_recipients=draft.cc_recipients,
            bcc_recipients=draft.bcc_recipients,
            reply_all_reviewed=plan.reply_all_reviewed,
            bcc_authorized=plan.bcc_authorized,
            policy_rules=policy_rules,
        )
        if findings or not recipient_result.allowed:
            if findings:
                COMMUNICATION_DRAFT_VALIDATION_FAILURES_TOTAL.inc()
            if not recipient_result.allowed:
                COMMUNICATION_RECIPIENT_POLICY_BLOCKS_TOTAL.inc()
            plan.readiness_status = ReadinessStatus.BLOCKED
            plan.readiness_blockers = findings + list(recipient_result.blockers)
            await self.session.commit()
            raise StateConflictError(
                "Draft is not ready for send approval.",
                details={"blockers": findings + list(recipient_result.blockers)},
            )
        _, attachment_blockers = await validate_draft_attachments(
            self.session,
            draft.id,
            require_graph_uploaded=True,
        )
        if plan.response_type == ResponseType.DOCUMENT_RESPONSE and attachment_count == 0:
            attachment_blockers.append("REQUIRED_DOCUMENT_MISSING")
        requested_statuses = list(
            await self.session.scalars(
                select(TaskRequestedItem.status).where(TaskRequestedItem.task_id == draft.task_id)
            )
        )
        readiness = ResponseReadinessService().evaluate(
            response_type=plan.response_type,
            requested_item_statuses=requested_statuses,
            recipient_count=len(draft.to_recipients),
            graph_draft_exists=True,
            draft_reviewed=True,
            document_blockers=attachment_blockers,
            task_status=task.status,
            task_owner=task.assigned_to,
            destination_folder_id=task.destination_folder_id,
            response_deadline=task.due_date,
            check_task_context=True,
        )
        plan.readiness_status = readiness.status
        plan.readiness_blockers = list(readiness.blockers)
        unexpected_blockers = [
            blocker for blocker in readiness.blockers if blocker != "SEND_APPROVAL_MISSING"
        ]
        if readiness.status in {ReadinessStatus.NOT_READY, ReadinessStatus.BLOCKED} or (
            unexpected_blockers
        ):
            await self.session.commit()
            raise StateConflictError(
                "Response plan is not ready for send approval.",
                details={"blockers": unexpected_blockers},
            )
        draft.draft_status = CommunicationDraftStatus.PENDING_SEND_APPROVAL
        draft.submitted_for_approval_at = utcnow()
        draft.last_edited_by_actor = actor.actor_id
        self.session.add(
            TaskEvent(
                task_id=draft.task_id,
                event_type="DRAFT_SUBMITTED_FOR_SEND_APPROVAL",
                actor_id=actor.actor_id,
                event_metadata={"draft_id": str(draft.id), "revision": draft.local_revision},
                occurred_at=utcnow(),
            )
        )
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="outbound_draft",
            entity_id=draft.id,
            action="draft_submitted_for_send_approval",
            after={"revision": draft.local_revision, "status": draft.draft_status},
        )
        await self.session.commit()
        return draft

    async def request_changes(
        self,
        draft_id: uuid.UUID,
        reason: str,
        actor: CurrentActor,
        *,
        expected_revision: int,
        expected_graph_change_key: str | None,
        expected_graph_etag: str | None,
    ) -> OutboundDraft:
        if not reason.strip():
            raise ValueError("A change reason is required.")
        draft = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.id == draft_id).with_for_update()
        )
        if draft is None:
            raise NotFoundError("Draft does not exist.")
        self._assert_expected(
            draft,
            expected_revision,
            expected_graph_change_key,
            expected_graph_etag,
        )
        await invalidate_approval(self.session, draft, reason)
        draft.draft_status = CommunicationDraftStatus.CHANGES_REQUESTED
        self.session.add(
            TaskEvent(
                task_id=draft.task_id,
                event_type="DRAFT_CHANGES_REQUESTED",
                actor_id=actor.actor_id,
                event_metadata={"reason": reason},
                occurred_at=utcnow(),
            )
        )
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="outbound_draft",
            entity_id=draft.id,
            action="draft_changes_requested",
            after={"status": draft.draft_status},
        )
        await self.session.commit()
        return draft

    async def reject(
        self,
        draft_id: uuid.UUID,
        reason: str,
        actor: CurrentActor,
        *,
        expected_revision: int,
        expected_graph_change_key: str | None,
        expected_graph_etag: str | None,
    ) -> OutboundDraft:
        draft = await self.request_changes(
            draft_id,
            reason,
            actor,
            expected_revision=expected_revision,
            expected_graph_change_key=expected_graph_change_key,
            expected_graph_etag=expected_graph_etag,
        )
        draft.draft_status = CommunicationDraftStatus.CANCELLED
        await self.session.commit()
        return draft

    @staticmethod
    def _assert_expected(
        draft: OutboundDraft,
        expected_revision: int,
        expected_graph_change_key: str | None,
        expected_graph_etag: str | None,
    ) -> None:
        if draft.local_revision != expected_revision:
            raise StateConflictError(
                "Draft revision changed.",
                details={"current_revision": draft.local_revision},
            )
        if draft.graph_draft_message_id and (
            draft.graph_change_key != expected_graph_change_key
            or draft.graph_etag != expected_graph_etag
        ):
            raise StateConflictError("Graph draft changed; synchronize before review action.")

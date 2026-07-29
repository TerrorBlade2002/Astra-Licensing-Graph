"""Exact-snapshot send approval with enforced separation of duties."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.auth.roles import Role, has_role
from app.communications.attachments import validate_draft_attachments
from app.communications.audit import add_communication_audit
from app.communications.enums import ApprovalDecision, CommunicationDraftStatus
from app.communications.hashes import approval_snapshot_hash
from app.communications.recipients import RecipientPolicyService
from app.communications.snapshots import invalidate_approval
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import (
    COMMUNICATION_RECIPIENT_POLICY_BLOCKS_TOTAL,
    COMMUNICATION_SEND_APPROVALS_TOTAL,
)
from app.models import (
    CommunicationJob,
    Mailbox,
    OutboundDraft,
    OutboundDraftVersion,
    RecipientPolicyRule,
    ResponsePlan,
    SendApproval,
    TaskEvent,
)
from app.models.mixins import utcnow


class SendApprovalService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings

    async def approve(
        self,
        draft_id: uuid.UUID,
        *,
        expected_revision: int,
        expected_snapshot_sha256: str,
        expected_graph_draft_id: str,
        expected_graph_change_key: str | None,
        expected_graph_etag: str | None,
        notes: str | None,
        actor: CurrentActor,
    ) -> SendApproval:
        draft = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.id == draft_id).with_for_update()
        )
        if draft is None or draft.response_plan_id is None or draft.current_version_id is None:
            raise NotFoundError("Draft or exact revision is missing.")
        if draft.draft_status != CommunicationDraftStatus.PENDING_SEND_APPROVAL:
            raise StateConflictError("Draft is not pending send approval.")
        if draft.local_revision != expected_revision:
            raise StateConflictError("Draft revision changed after review.")
        if draft.graph_draft_message_id != expected_graph_draft_id:
            raise StateConflictError("Graph draft identity changed after review.")
        if (
            draft.graph_change_key != expected_graph_change_key
            or draft.graph_etag != expected_graph_etag
        ):
            raise StateConflictError("Graph draft changed after review.")
        must_be_separate = (
            self.settings.communication_require_separate_send_approver
            or not self.settings.communication_allow_self_approval
        )
        if must_be_separate and actor.actor_id in {
            draft.created_by_actor,
            draft.last_edited_by_actor,
        }:
            raise StateConflictError("The draft author or last editor cannot approve this send.")
        if not has_role(actor.roles, Role.SENDER):
            raise StateConflictError("Licensing.Sender role is required for send approval.")
        version = await self.session.get(OutboundDraftVersion, draft.current_version_id)
        plan = await self.session.get(ResponsePlan, draft.response_plan_id)
        mailbox = await self.session.get(Mailbox, draft.mailbox_id)
        if version is None or plan is None or mailbox is None:
            raise NotFoundError("Draft snapshot context is missing.")
        internal_domain = mailbox.address.rsplit("@", 1)[-1].lower()
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
            internal_domains={internal_domain},
            policy_rules=policy_rules,
            manager_approved=has_role(actor.roles, Role.MANAGER),
            enforce_manager_rules=True,
        )
        if not recipient_result.allowed:
            COMMUNICATION_RECIPIENT_POLICY_BLOCKS_TOTAL.inc()
            raise StateConflictError(
                "Recipient policy blocks send approval.",
                details={"blockers": list(recipient_result.blockers)},
            )
        if (
            self.settings.communication_external_recipient_requires_manager
            and "EXTERNAL_RECIPIENT" in recipient_result.warnings
            and not has_role(actor.roles, Role.MANAGER)
        ):
            raise StateConflictError("External recipients require Licensing.Manager approval.")
        _, attachment_blockers = await validate_draft_attachments(
            self.session,
            draft.id,
            require_graph_uploaded=True,
        )
        if attachment_blockers:
            raise StateConflictError(
                "Attachment policy blocks send approval.",
                details={"blockers": attachment_blockers},
            )
        computed = approval_snapshot_hash(
            subject=draft.subject,
            body_sha256=draft.body_sha256,
            recipient_sha256=draft.recipient_set_sha256,
            attachment_sha256=draft.attachment_set_sha256,
            revision=draft.local_revision,
            graph_draft_message_id=draft.graph_draft_message_id or "",
            graph_change_key=draft.graph_change_key,
            graph_etag=draft.graph_etag,
            response_plan_id=str(plan.id),
            template_version_id=str(plan.selected_template_version_id)
            if plan.selected_template_version_id
            else None,
        )
        if computed != expected_snapshot_sha256:
            raise StateConflictError("Approval snapshot does not match the reviewed content.")
        if self.settings.communication_require_two_person_approval:
            first = await self.session.scalar(
                select(SendApproval).where(
                    SendApproval.outbound_draft_id == draft.id,
                    SendApproval.decision == ApprovalDecision.PENDING_SECOND_APPROVAL,
                    SendApproval.invalidated_at.is_(None),
                )
            )
            if first is not None and (
                first.approval_snapshot_sha256 != computed or first.draft_version_id != version.id
            ):
                first.decision = ApprovalDecision.INVALIDATED
                first.invalidated_at = utcnow()
                first.invalidation_reason = "draft changed before second approval"
                first = None
            if first is None:
                row = self._row(
                    draft, version, actor, computed, notes, ApprovalDecision.PENDING_SECOND_APPROVAL
                )
                self.session.add(row)
                await self.session.flush()
                add_communication_audit(
                    self.session,
                    actor=actor,
                    entity_type="send_approval",
                    entity_id=row.id,
                    action="first_send_approval_recorded",
                    after={"decision": row.decision},
                    metadata={"draft_id": str(draft.id), "revision": draft.local_revision},
                )
                await self.session.commit()
                return row
            if first.approver_actor == actor.actor_id:
                raise StateConflictError("A different Sender must provide the second approval.")
        approval = self._row(draft, version, actor, computed, notes, ApprovalDecision.APPROVED)
        now = utcnow()
        approval.approved_at = now
        draft.approval_snapshot_sha256 = computed
        draft.approved_at = now
        draft.draft_status = CommunicationDraftStatus.APPROVED_TO_SEND
        self.session.add(approval)
        self.session.add(
            TaskEvent(
                task_id=draft.task_id,
                event_type="SEND_APPROVED",
                actor_id=actor.actor_id,
                event_metadata={"snapshot_sha256": computed, "revision": draft.local_revision},
                occurred_at=now,
            )
        )
        await self.session.flush()
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="send_approval",
            entity_id=approval.id,
            action="exact_snapshot_send_approved",
            after={"decision": approval.decision},
            metadata={"draft_id": str(draft.id), "revision": draft.local_revision},
        )
        await self.session.commit()
        COMMUNICATION_SEND_APPROVALS_TOTAL.inc()
        return approval

    @staticmethod
    def _row(
        draft: OutboundDraft,
        version: OutboundDraftVersion,
        actor: CurrentActor,
        snapshot: str,
        notes: str | None,
        decision: str,
    ) -> SendApproval:
        return SendApproval(
            outbound_draft_id=draft.id,
            draft_version_id=version.id,
            decision=decision,
            approver_actor=actor.actor_id,
            approval_snapshot_sha256=snapshot,
            body_sha256=draft.body_sha256,
            recipient_set_sha256=draft.recipient_set_sha256,
            attachment_set_sha256=draft.attachment_set_sha256,
            graph_draft_message_id=draft.graph_draft_message_id or "",
            graph_change_key=draft.graph_change_key,
            graph_etag=draft.graph_etag,
            approval_notes=notes,
        )

    async def invalidate(
        self, draft_id: uuid.UUID, reason: str, actor: CurrentActor
    ) -> OutboundDraft:
        draft = await self.session.get(OutboundDraft, draft_id)
        if draft is None:
            raise NotFoundError("Draft does not exist.")
        await invalidate_approval(self.session, draft, reason)
        draft.draft_status = CommunicationDraftStatus.CHANGES_REQUESTED
        await self.session.commit()
        return draft

    async def decline(
        self,
        draft_id: uuid.UUID,
        *,
        decision: ApprovalDecision,
        reason: str,
        expected_revision: int,
        expected_graph_change_key: str | None,
        expected_graph_etag: str | None,
        actor: CurrentActor,
    ) -> OutboundDraft:
        if decision not in {
            ApprovalDecision.REJECTED,
            ApprovalDecision.CHANGES_REQUESTED,
        }:
            raise ValueError("Unsupported send-approval decision.")
        if not has_role(actor.roles, Role.SENDER):
            raise StateConflictError("Licensing.Sender role is required.")
        draft = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.id == draft_id).with_for_update()
        )
        if (
            draft is None
            or draft.response_plan_id is None
            or draft.current_version_id is None
            or not draft.graph_draft_message_id
        ):
            raise NotFoundError("Draft or exact revision is missing.")
        self._assert_expected(
            draft,
            expected_revision,
            expected_graph_change_key,
            expected_graph_etag,
        )
        if draft.draft_status not in {
            CommunicationDraftStatus.PENDING_SEND_APPROVAL,
            CommunicationDraftStatus.APPROVED_TO_SEND,
        }:
            raise StateConflictError("Draft is not in a send-approval decision state.")
        version = await self.session.get(OutboundDraftVersion, draft.current_version_id)
        plan = await self.session.get(ResponsePlan, draft.response_plan_id)
        if version is None or plan is None:
            raise NotFoundError("Draft snapshot context is missing.")
        snapshot = approval_snapshot_hash(
            subject=draft.subject,
            body_sha256=draft.body_sha256,
            recipient_sha256=draft.recipient_set_sha256,
            attachment_sha256=draft.attachment_set_sha256,
            revision=draft.local_revision,
            graph_draft_message_id=draft.graph_draft_message_id,
            graph_change_key=draft.graph_change_key,
            graph_etag=draft.graph_etag,
            response_plan_id=str(plan.id),
            template_version_id=str(plan.selected_template_version_id)
            if plan.selected_template_version_id
            else None,
        )
        await invalidate_approval(self.session, draft, reason)
        row = self._row(draft, version, actor, snapshot, reason, decision)
        row.rejected_at = utcnow()
        self.session.add(row)
        draft.draft_status = (
            CommunicationDraftStatus.CANCELLED
            if decision == ApprovalDecision.REJECTED
            else CommunicationDraftStatus.CHANGES_REQUESTED
        )
        self.session.add(
            TaskEvent(
                task_id=draft.task_id,
                event_type=f"SEND_APPROVAL_{decision}",
                actor_id=actor.actor_id,
                event_metadata={"draft_id": str(draft.id), "reason": reason},
                occurred_at=utcnow(),
            )
        )
        await self.session.flush()
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="send_approval",
            entity_id=row.id,
            action="send_approval_declined",
            after={"decision": row.decision, "draft_status": draft.draft_status},
            metadata={"draft_id": str(draft.id), "revision": draft.local_revision},
        )
        await self.session.commit()
        return draft

    async def cancel_unsent(
        self,
        draft_id: uuid.UUID,
        *,
        reason: str,
        expected_revision: int,
        expected_graph_change_key: str | None,
        expected_graph_etag: str | None,
        actor: CurrentActor,
    ) -> OutboundDraft:
        if not has_role(actor.roles, Role.SENDER):
            raise StateConflictError("Licensing.Sender role is required.")
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
        if draft.draft_status not in {
            CommunicationDraftStatus.APPROVED_TO_SEND,
            CommunicationDraftStatus.SEND_QUEUED,
        }:
            raise StateConflictError("Only an approved, unsent draft can be cancelled.")
        jobs = list(
            await self.session.scalars(
                select(CommunicationJob)
                .where(
                    CommunicationJob.outbound_draft_id == draft.id,
                    CommunicationJob.job_type == "SEND_DRAFT",
                    CommunicationJob.status.in_(["PENDING", "FAILED_RETRYABLE", "RUNNING"]),
                )
                .with_for_update()
            )
        )
        if any(job.status == "RUNNING" for job in jobs):
            raise StateConflictError("The send worker already holds this draft.")
        for job in jobs:
            job.status = "CANCELLED"
            job.lease_owner = None
            job.lease_expires_at = None
        await invalidate_approval(self.session, draft, reason)
        draft.draft_status = CommunicationDraftStatus.CANCELLED
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="outbound_draft",
            entity_id=draft.id,
            action="approved_unsent_draft_cancelled",
            after={"status": draft.draft_status},
            metadata={"cancelled_job_count": len(jobs), "reason": reason},
        )
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
            raise StateConflictError("Draft revision changed after review.")
        if (
            draft.graph_change_key != expected_graph_change_key
            or draft.graph_etag != expected_graph_etag
        ):
            raise StateConflictError("Graph draft changed after review.")

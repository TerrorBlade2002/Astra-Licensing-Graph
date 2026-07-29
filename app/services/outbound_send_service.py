"""Approval-rechecking send saga; ambiguous sends are never replayed."""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.communications.attachments import validate_draft_attachments
from app.communications.audit import add_system_communication_audit
from app.communications.enums import (
    ApprovalDecision,
    CommunicationDraftStatus,
    CommunicationJobType,
    SendAttemptStatus,
)
from app.communications.hashes import approval_snapshot_hash, recipient_set_hash, sha256_text
from app.communications.recipients import RecipientPolicyService
from app.communications.snapshots import invalidate_approval
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import (
    COMMUNICATION_RECIPIENT_POLICY_BLOCKS_TOTAL,
    COMMUNICATION_SEND_ACCEPTED_TOTAL,
    COMMUNICATION_SEND_AMBIGUOUS_TOTAL,
    COMMUNICATION_SEND_FAILED_REVIEW_TOTAL,
)
from app.graph.client import GraphHttpClient
from app.graph.drafts import GraphDraftClient
from app.graph.errors import GraphApiError, GraphAuthError
from app.graph.send import GraphSendClient
from app.models import (
    Mailbox,
    OutboundDraft,
    OutboundSendAttempt,
    RecipientPolicyRule,
    ResponsePlan,
    SendApproval,
)
from app.models.mixins import utcnow
from app.repositories.communication_jobs import CommunicationJobRepository
from app.services.graph_draft_service import _body, _recipients, graph_attachments_match


class OutboundSendService:
    def __init__(self, session: AsyncSession, settings: Settings, graph: GraphHttpClient) -> None:
        self.session, self.settings, self.graph = session, settings, graph

    async def execute(
        self, draft_id: uuid.UUID, *, job_id: uuid.UUID | None = None
    ) -> OutboundSendAttempt:
        draft = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.id == draft_id).with_for_update()
        )
        if draft is None or draft.response_plan_id is None or not draft.graph_draft_message_id:
            raise NotFoundError("Sendable Graph draft does not exist.")
        if draft.draft_status in {
            CommunicationDraftStatus.SEND_ACCEPTED,
            CommunicationDraftStatus.SEND_AMBIGUOUS,
            CommunicationDraftStatus.SENT_COPY_VERIFIED,
        }:
            completed_attempt: OutboundSendAttempt | None = await self.session.scalar(
                select(OutboundSendAttempt)
                .where(OutboundSendAttempt.outbound_draft_id == draft.id)
                .order_by(OutboundSendAttempt.attempt_number.desc())
            )
            if completed_attempt:
                return completed_attempt
        if draft.draft_status == CommunicationDraftStatus.SENDING:
            started_attempt: OutboundSendAttempt | None = await self.session.scalar(
                select(OutboundSendAttempt)
                .where(OutboundSendAttempt.outbound_draft_id == draft.id)
                .order_by(OutboundSendAttempt.attempt_number.desc())
            )
            if started_attempt and started_attempt.status == SendAttemptStatus.STARTED:
                started_attempt.status = SendAttemptStatus.AMBIGUOUS
                started_attempt.error_code = "STALE_SEND_LEASE"
                started_attempt.error_message = (
                    "The send worker stopped after persisting intent; reconciliation is required."
                )
                draft.draft_status = CommunicationDraftStatus.SEND_AMBIGUOUS
                await CommunicationJobRepository(self.session).enqueue(
                    job_type=CommunicationJobType.RECONCILE_SEND,
                    idempotency_key=f"stale-send-reconcile:{started_attempt.id}",
                    draft_id=draft.id,
                    email_id=draft.email_id,
                    task_id=draft.task_id,
                    priority=1,
                    max_attempts=self.settings.communication_send_reconciliation_max_attempts,
                    delay_seconds=self.settings.communication_send_reconciliation_initial_delay_seconds,
                )
                await self.session.commit()
                return started_attempt
        if draft.draft_status not in {
            CommunicationDraftStatus.SEND_QUEUED,
            CommunicationDraftStatus.APPROVED_TO_SEND,
            CommunicationDraftStatus.SEND_FAILED_RETRYABLE,
        }:
            raise StateConflictError("Draft is not queued with a safe send state.")
        approval = await self.session.scalar(
            select(SendApproval).where(
                SendApproval.outbound_draft_id == draft.id,
                SendApproval.decision == ApprovalDecision.APPROVED,
                SendApproval.invalidated_at.is_(None),
            )
        )
        plan = await self.session.get(ResponsePlan, draft.response_plan_id)
        mailbox = await self.session.get(Mailbox, draft.mailbox_id)
        if approval is None or plan is None or mailbox is None:
            return await self._preflight_failed(
                draft, "Active approval or mailbox context is missing."
            )
        expected_mailbox = (self.settings.graph_expected_mailbox_address or "").strip().lower()
        if not expected_mailbox or mailbox.address.strip().lower() != expected_mailbox:
            return await self._preflight_failed(
                draft, "Mail.Send mailbox boundary validation failed."
            )
        policy_rules = list(
            await self.session.scalars(
                select(RecipientPolicyRule).where(RecipientPolicyRule.enabled.is_(True))
            )
        )
        recipient_policy = RecipientPolicyService(self.settings).evaluate(
            mode=plan.proposed_recipient_mode,
            to_recipients=draft.to_recipients,
            cc_recipients=draft.cc_recipients,
            bcc_recipients=draft.bcc_recipients,
            reply_all_reviewed=plan.reply_all_reviewed,
            bcc_authorized=plan.bcc_authorized,
            internal_domains={mailbox.address.rsplit("@", 1)[-1].lower()},
            policy_rules=policy_rules,
        )
        if not recipient_policy.allowed:
            COMMUNICATION_RECIPIENT_POLICY_BLOCKS_TOTAL.inc()
            return await self._preflight_failed(
                draft,
                "Recipient policy changed after approval.",
            )
        persisted = approval_snapshot_hash(
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
        if persisted != approval.approval_snapshot_sha256:
            return await self._preflight_failed(draft, "DRAFT_CHANGED_AFTER_APPROVAL")
        _, attachment_blockers = await validate_draft_attachments(
            self.session,
            draft.id,
            require_graph_uploaded=True,
        )
        if attachment_blockers:
            return await self._preflight_failed(draft, "ATTACHMENT_CHANGED_AFTER_APPROVAL")
        try:
            graph = await GraphDraftClient(self.graph).get(
                mailbox.graph_user_id or mailbox.address, draft.graph_draft_message_id
            )
        except GraphApiError as exc:
            if exc.status_code == 404:
                return await self._preflight_failed(
                    draft, "Graph draft is missing; explicit review is required."
                )
            raise
        if graph.get("isDraft") is not True:
            draft.draft_status = CommunicationDraftStatus.SEND_AMBIGUOUS
            await CommunicationJobRepository(self.session).enqueue(
                job_type=CommunicationJobType.RECONCILE_SEND,
                idempotency_key=f"preflight-no-longer-draft:{draft.id}:{draft.local_revision}",
                draft_id=draft.id,
                email_id=draft.email_id,
                task_id=draft.task_id,
                priority=1,
                max_attempts=self.settings.communication_send_reconciliation_max_attempts,
                delay_seconds=self.settings.communication_send_reconciliation_initial_delay_seconds,
            )
            await self.session.commit()
            raise StateConflictError(
                "Graph draft is no longer a draft; send reconciliation was queued."
            )
        text_body, html_body = _body(graph)
        graph_body = sha256_text(
            f"{graph.get('subject') or ''}\n{text_body or ''}\n{html_body or ''}"
        )
        graph_recipients = recipient_set_hash(
            _recipients(graph.get("toRecipients")),
            _recipients(graph.get("ccRecipients")),
            _recipients(graph.get("bccRecipients")),
        )
        graph_attachments_unchanged = await graph_attachments_match(
            self.session,
            GraphDraftClient(self.graph),
            mailbox.graph_user_id or mailbox.address,
            draft,
            graph_has_attachments=graph.get("hasAttachments") is True,
        )
        graph_identity_unchanged = (
            str(graph.get("changeKey") or "") or None
        ) == approval.graph_change_key and (
            str(graph.get("@odata.etag") or "") or None
        ) == approval.graph_etag
        if (
            graph_body != approval.body_sha256
            or graph_recipients != approval.recipient_set_sha256
            or not graph_attachments_unchanged
            or not graph_identity_unchanged
        ):
            await invalidate_approval(
                self.session, draft, "Graph draft changed after send approval"
            )
            return await self._preflight_failed(draft, "DRAFT_CHANGED_AFTER_APPROVAL")
        count = await self.session.scalar(
            select(func.count(OutboundSendAttempt.id)).where(
                OutboundSendAttempt.outbound_draft_id == draft.id
            )
        )
        attempt_number = int(count or 0) + 1
        attempt = OutboundSendAttempt(
            outbound_draft_id=draft.id,
            send_approval_id=approval.id,
            job_id=job_id,
            attempt_number=attempt_number,
            idempotency_key=(
                f"send-attempt:{draft.id}:{approval.approval_snapshot_sha256}:{attempt_number}"
            ),
            pre_send_snapshot_sha256=persisted,
            graph_draft_message_id=draft.graph_draft_message_id,
            status=SendAttemptStatus.STARTED,
            started_at=utcnow(),
        )
        self.session.add(attempt)
        await self.session.flush()
        draft.draft_status = CommunicationDraftStatus.SENDING
        add_system_communication_audit(
            self.session,
            entity_type="outbound_send_attempt",
            entity_id=attempt.id,
            action="send_intent_persisted",
            after={"status": attempt.status, "attempt_number": attempt.attempt_number},
            metadata={"draft_id": str(draft.id), "job_id": str(job_id) if job_id else None},
        )
        await self.session.commit()  # intent and exact snapshot before external POST
        sender = GraphSendClient(self.graph)
        try:
            accepted = await sender.send_existing_draft(
                expected_mailbox, draft.graph_draft_message_id
            )
        except GraphApiError as exc:
            if exc.status_code == 401:
                try:
                    accepted = await sender.send_existing_draft(
                        expected_mailbox,
                        draft.graph_draft_message_id,
                        force_token_refresh=True,
                    )
                except GraphApiError as second:
                    return await self._failed(attempt, draft, second)
            else:
                return await self._failed(attempt, draft, exc)
        except GraphAuthError as exc:
            return await self._safe_retry(
                attempt,
                draft,
                error_code=exc.error_code,
                error_message="Token acquisition failed before the send request.",
            )
        except httpx.ConnectError as exc:
            return await self._safe_retry(
                attempt,
                draft,
                error_code=type(exc).__name__,
                error_message="Connection failed before the send request was transmitted.",
            )
        except (httpx.TimeoutException, httpx.ReadError, httpx.WriteError) as exc:
            attempt.status = SendAttemptStatus.AMBIGUOUS
            attempt.error_code = type(exc).__name__
            attempt.error_message = "Send outcome is ambiguous; automatic resend is forbidden."
            draft.draft_status = CommunicationDraftStatus.SEND_AMBIGUOUS
            COMMUNICATION_SEND_AMBIGUOUS_TOTAL.inc()
            await CommunicationJobRepository(self.session).enqueue(
                job_type=CommunicationJobType.RECONCILE_SEND,
                idempotency_key=f"ambiguous-reconcile:{attempt.id}",
                draft_id=draft.id,
                email_id=draft.email_id,
                task_id=draft.task_id,
                priority=1,
                max_attempts=self.settings.communication_send_reconciliation_max_attempts,
                delay_seconds=self.settings.communication_send_reconciliation_initial_delay_seconds,
            )
            add_system_communication_audit(
                self.session,
                entity_type="outbound_send_attempt",
                entity_id=attempt.id,
                action="send_outcome_marked_ambiguous",
                after={"status": attempt.status},
            )
            await self.session.commit()
            return attempt
        attempt.status = SendAttemptStatus.ACCEPTED
        attempt.http_status = accepted.http_status
        attempt.graph_request_id = accepted.request_id
        attempt.graph_client_request_id = accepted.client_request_id
        attempt.accepted_at = utcnow()
        draft.draft_status = CommunicationDraftStatus.SEND_ACCEPTED
        draft.delivery_status = "UNKNOWN"
        COMMUNICATION_SEND_ACCEPTED_TOTAL.inc()
        await CommunicationJobRepository(self.session).enqueue(
            job_type=CommunicationJobType.RECONCILE_SEND,
            idempotency_key=f"accepted-reconcile:{attempt.id}",
            draft_id=draft.id,
            email_id=draft.email_id,
            task_id=draft.task_id,
            priority=20,
            max_attempts=self.settings.communication_send_reconciliation_max_attempts,
            delay_seconds=self.settings.communication_send_reconciliation_initial_delay_seconds,
        )
        add_system_communication_audit(
            self.session,
            entity_type="outbound_send_attempt",
            entity_id=attempt.id,
            action="graph_send_accepted",
            after={"status": attempt.status, "http_status": attempt.http_status},
        )
        await self.session.commit()
        return attempt

    async def _preflight_failed(self, draft: OutboundDraft, message: str) -> OutboundSendAttempt:
        draft.draft_status = CommunicationDraftStatus.SEND_FAILED_REVIEW
        COMMUNICATION_SEND_FAILED_REVIEW_TOTAL.inc()
        add_system_communication_audit(
            self.session,
            entity_type="outbound_draft",
            entity_id=draft.id,
            action="send_preflight_failed_review",
            after={"status": draft.draft_status},
        )
        await self.session.commit()
        raise StateConflictError(message)

    async def _failed(
        self,
        attempt: OutboundSendAttempt,
        draft: OutboundDraft,
        error: GraphApiError,
    ) -> OutboundSendAttempt:
        attempt.http_status = error.status_code
        attempt.graph_request_id = error.request_id
        attempt.graph_client_request_id = error.client_request_id
        attempt.error_code = error.graph_error_code or f"HTTP_{error.status_code}"
        attempt.error_message = error.safe_message
        if error.status_code in {408, 500, 502, 503, 504}:
            # These responses can arrive after Graph/Exchange accepted the
            # non-idempotent send. Reconcile Sent Items; never replay the POST.
            attempt.status = SendAttemptStatus.AMBIGUOUS
            draft.draft_status = CommunicationDraftStatus.SEND_AMBIGUOUS
            attempt.error_message = "Send outcome is ambiguous; automatic resend is forbidden."
            COMMUNICATION_SEND_AMBIGUOUS_TOTAL.inc()
            await CommunicationJobRepository(self.session).enqueue(
                job_type=CommunicationJobType.RECONCILE_SEND,
                idempotency_key=f"ambiguous-http-reconcile:{attempt.id}",
                draft_id=draft.id,
                email_id=draft.email_id,
                task_id=draft.task_id,
                priority=1,
                max_attempts=self.settings.communication_send_reconciliation_max_attempts,
                delay_seconds=self.settings.communication_send_reconciliation_initial_delay_seconds,
            )
            add_system_communication_audit(
                self.session,
                entity_type="outbound_send_attempt",
                entity_id=attempt.id,
                action="send_http_outcome_marked_ambiguous",
                after={"status": attempt.status, "http_status": attempt.http_status},
            )
            await self.session.commit()
            return attempt
        if error.status_code == 429:
            return await self._safe_retry(
                attempt,
                draft,
                error_code=attempt.error_code,
                error_message=attempt.error_message,
            )
        attempt.status = SendAttemptStatus.FAILED_REVIEW
        draft.draft_status = CommunicationDraftStatus.SEND_FAILED_REVIEW
        COMMUNICATION_SEND_FAILED_REVIEW_TOTAL.inc()
        add_system_communication_audit(
            self.session,
            entity_type="outbound_send_attempt",
            entity_id=attempt.id,
            action="send_failed_review",
            after={"status": attempt.status, "http_status": attempt.http_status},
        )
        await self.session.commit()
        return attempt

    async def _safe_retry(
        self,
        attempt: OutboundSendAttempt,
        draft: OutboundDraft,
        *,
        error_code: str | None,
        error_message: str | None,
    ) -> OutboundSendAttempt:
        attempt.error_code = error_code
        attempt.error_message = error_message
        if attempt.attempt_number >= self.settings.communication_send_job_max_attempts:
            attempt.status = SendAttemptStatus.FAILED_REVIEW
            draft.draft_status = CommunicationDraftStatus.SEND_FAILED_REVIEW
            COMMUNICATION_SEND_FAILED_REVIEW_TOTAL.inc()
        else:
            attempt.status = SendAttemptStatus.FAILED_RETRYABLE
            draft.draft_status = CommunicationDraftStatus.SEND_FAILED_RETRYABLE
            await CommunicationJobRepository(self.session).enqueue(
                job_type=CommunicationJobType.SEND_DRAFT,
                idempotency_key=f"safe-send-retry:{attempt.id}",
                draft_id=draft.id,
                email_id=draft.email_id,
                task_id=draft.task_id,
                priority=10,
                max_attempts=1,
            )
        add_system_communication_audit(
            self.session,
            entity_type="outbound_send_attempt",
            entity_id=attempt.id,
            action=(
                "send_safe_retry_queued"
                if attempt.status == SendAttemptStatus.FAILED_RETRYABLE
                else "send_safe_retry_exhausted"
            ),
            after={"status": attempt.status},
        )
        await self.session.commit()
        return attempt

"""Controlled communication plans, drafts, approvals, jobs, and status APIs."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select

from app.ai.openai_response_drafting import OpenAIResponseSuggestionProvider
from app.api.dependencies import ActorDep, GraphClientDep, SessionDep, SettingsDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role, has_role
from app.communications.audit import add_communication_audit
from app.communications.enums import (
    ApprovalDecision,
    CommunicationDraftStatus,
    CommunicationJobType,
    RecipientMode,
    ResponseType,
)
from app.communications.hashes import approval_snapshot_hash
from app.communications.snapshots import invalidate_approval
from app.communications.validation import validate_draft_content
from app.core.exceptions import NotFoundError, StateConflictError
from app.models import (
    Classification,
    Document,
    DocumentVersion,
    Email,
    LicensingTask,
    Mailbox,
    MailboxFolder,
    MessageMoveAttempt,
    OutboundDraft,
    OutboundDraftAttachment,
    OutboundDraftVersion,
    OutboundSendAttempt,
    RecipientPolicyRule,
    ResponsePlan,
    ResponseTemplate,
    ResponseTemplateVersion,
    SendApproval,
    TaskRequestedItem,
    WorkflowCompletionRecord,
)
from app.repositories.communication_jobs import CommunicationJobRepository
from app.schemas.communications import (
    AttachmentSelect,
    DraftCreate,
    DraftMutationExpectation,
    DraftPatch,
    RecipientPolicyCreate,
    RecipientPolicyPatch,
    ResponsePlanCreate,
    ResponsePlanPatch,
    ReviewReason,
    SendApprovalIn,
    SendEnqueueIn,
    TemplateCreate,
    TemplateVersionCreate,
)
from app.services.communication_enqueue_service import CommunicationEnqueueService
from app.services.draft_attachment_service import DraftAttachmentService
from app.services.draft_generation_service import DraftGenerationService
from app.services.draft_review_service import DraftReviewService
from app.services.graph_draft_attachment_service import GraphDraftAttachmentService
from app.services.graph_draft_service import GraphDraftService
from app.services.response_plan_service import ResponsePlanService
from app.services.response_suggestion_service import ResponseSuggestionService
from app.services.response_template_service import ResponseTemplateService
from app.services.send_approval_service import SendApprovalService
from app.services.workflow_completion_service import WorkflowCompletionService

router = APIRouter(tags=["controlled communications"])
Reviewer = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]
Sender = Annotated[CurrentActor, Depends(require_role(Role.SENDER))]
Manager = Annotated[CurrentActor, Depends(require_role(Role.MANAGER))]
Admin = Annotated[CurrentActor, Depends(require_role(Role.ADMIN))]


def _plan(row: ResponsePlan) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "task_id": str(row.task_id),
        "email_id": str(row.email_id),
        "classification_id": str(row.classification_id),
        "response_type": row.response_type,
        "response_required": row.response_required,
        "readiness_status": row.readiness_status,
        "readiness_blockers": row.readiness_blockers,
        "selected_template_version_id": str(row.selected_template_version_id)
        if row.selected_template_version_id
        else None,
        "recipient_mode": row.proposed_recipient_mode,
        "reply_all_reviewed": row.reply_all_reviewed,
        "bcc_authorized": row.bcc_authorized,
        "destination_folder_name": row.suggested_destination_folder_name,
    }


async def _draft(session: SessionDep, row: OutboundDraft) -> dict[str, Any]:
    attachments = list(
        await session.scalars(
            select(OutboundDraftAttachment).where(
                OutboundDraftAttachment.outbound_draft_id == row.id,
                OutboundDraftAttachment.removed_at.is_(None),
            )
        )
    )
    plan = await session.get(ResponsePlan, row.response_plan_id) if row.response_plan_id else None
    task = await session.get(LicensingTask, row.task_id)
    email = await session.get(Email, row.email_id) if row.email_id else None
    mailbox = await session.get(Mailbox, row.mailbox_id)
    classification = await session.get(Classification, plan.classification_id) if plan else None
    requested_items = list(
        await session.scalars(
            select(TaskRequestedItem)
            .where(TaskRequestedItem.task_id == row.task_id)
            .order_by(TaskRequestedItem.sort_order)
        )
    )
    approvals = list(
        await session.scalars(
            select(SendApproval)
            .where(SendApproval.outbound_draft_id == row.id)
            .order_by(SendApproval.created_at)
        )
    )
    sends = list(
        await session.scalars(
            select(OutboundSendAttempt)
            .where(OutboundSendAttempt.outbound_draft_id == row.id)
            .order_by(OutboundSendAttempt.attempt_number)
        )
    )
    moves = (
        list(
            await session.scalars(
                select(MessageMoveAttempt)
                .where(MessageMoveAttempt.email_id == row.email_id)
                .order_by(MessageMoveAttempt.attempt_number)
            )
        )
        if row.email_id
        else []
    )
    completion = (
        await session.scalar(
            select(WorkflowCompletionRecord).where(
                WorkflowCompletionRecord.email_id == row.email_id
            )
        )
        if row.email_id
        else None
    )
    template_version = (
        await session.get(ResponseTemplateVersion, plan.selected_template_version_id)
        if plan and plan.selected_template_version_id
        else None
    )
    template = (
        await session.get(ResponseTemplate, template_version.response_template_id)
        if template_version
        else None
    )
    pending_snapshot = None
    if row.graph_draft_message_id and plan:
        pending_snapshot = approval_snapshot_hash(
            subject=row.subject,
            body_sha256=row.body_sha256,
            recipient_sha256=row.recipient_set_sha256,
            attachment_sha256=row.attachment_set_sha256,
            revision=row.local_revision,
            graph_draft_message_id=row.graph_draft_message_id,
            graph_change_key=row.graph_change_key,
            graph_etag=row.graph_etag,
            response_plan_id=str(plan.id),
            template_version_id=str(plan.selected_template_version_id)
            if plan.selected_template_version_id
            else None,
        )
    attachment_rows: list[dict[str, Any]] = []
    for item in attachments:
        document = await session.get(Document, item.document_id) if item.document_id else None
        version = (
            await session.get(DocumentVersion, item.document_version_id)
            if item.document_version_id
            else None
        )
        attachment_rows.append(
            {
                "id": str(item.id),
                "filename": item.filename,
                "size_bytes": item.size_bytes,
                "content_sha256": item.content_sha256,
                "status": item.status,
                "document_id": str(item.document_id) if item.document_id else None,
                "document_version_id": str(item.document_version_id)
                if item.document_version_id
                else None,
                "graph_attachment_id": item.graph_attachment_id,
                "upload_method": item.upload_method,
                "document_approval_status": document.approval_status if document else None,
                "document_lifecycle_status": document.lifecycle_status if document else None,
                "document_confidentiality": document.confidentiality_level if document else None,
                "document_expiry_date": document.expiry_date if document else None,
                "document_storage_status": version.storage_status if version else None,
                "is_current_version": bool(
                    document and version and document.current_version_id == version.id
                ),
            }
        )
    validation_findings = validate_draft_content(
        subject=row.subject,
        body_text=row.body_text,
        body_html=row.body_html,
        attachment_count=len(attachments),
    )
    if not row.to_recipients:
        validation_findings.append("RECIPIENT_MISSING")
    validation_findings.extend(plan.readiness_blockers if plan else [])
    validation_findings.extend(
        f"ATTACHMENT_{item['status']}"
        for item in attachment_rows
        if item["status"] not in {"VALIDATED", "GRAPH_UPLOADED"}
    )
    internal_domain = (
        mailbox.address.rsplit("@", 1)[-1].lower() if mailbox and "@" in mailbox.address else None
    )
    recipient_domains = sorted(
        {
            str(recipient.get("address") or "").rsplit("@", 1)[-1].lower()
            for recipient in row.to_recipients + row.cc_recipients + row.bcc_recipients
            if "@" in str(recipient.get("address") or "")
        }
    )
    external_domains = [
        domain for domain in recipient_domains if not internal_domain or domain != internal_domain
    ]
    return {
        "id": str(row.id),
        "response_plan_id": str(row.response_plan_id) if row.response_plan_id else None,
        "task_id": str(row.task_id),
        "email_id": str(row.email_id) if row.email_id else None,
        "subject": row.subject,
        "body_text": row.body_text,
        "body_html": row.body_html,
        "to_recipients": row.to_recipients,
        "cc_recipients": row.cc_recipients,
        "bcc_recipients": row.bcc_recipients,
        "draft_status": row.draft_status,
        "local_revision": row.local_revision,
        "graph_draft_message_id": row.graph_draft_message_id,
        "graph_change_key": row.graph_change_key,
        "graph_etag": row.graph_etag,
        "approval_snapshot_sha256": row.approval_snapshot_sha256,
        "pending_approval_snapshot_sha256": pending_snapshot,
        "created_by_actor": row.created_by_actor,
        "last_edited_by_actor": row.last_edited_by_actor,
        "delivery_status": row.delivery_status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "graph_draft_created_at": row.graph_draft_created_at,
        "graph_last_synced_at": row.graph_last_synced_at,
        "submitted_for_approval_at": row.submitted_for_approval_at,
        "approved_at": row.approved_at,
        "send_queued_at": row.send_queued_at,
        "sent_at": row.sent_at,
        "sender_mailbox": mailbox.address if mailbox else None,
        "recipient_domains": recipient_domains,
        "external_recipient_domains": external_domains,
        "validation_findings": list(dict.fromkeys(validation_findings)),
        "attachments": attachment_rows,
        "response_plan": _plan(plan) if plan else None,
        "template": (
            {
                "id": str(template.id) if template else None,
                "name": template.name if template else None,
                "version_id": str(template_version.id),
                "version": template_version.version,
                "status": template_version.status,
                "template_sha256": template_version.template_sha256,
            }
            if template_version
            else None
        ),
        "task": (
            {
                "id": str(task.id),
                "title": task.title,
                "status": task.status,
                "owner": task.assigned_to,
                "due_date": task.due_date,
                "communication_status": task.communication_status,
                "destination_folder_name": task.destination_folder_name,
            }
            if task
            else None
        ),
        "requested_items": [
            {
                "id": str(item.id),
                "item_text": item.item_text,
                "category": item.category,
                "required": item.required,
                "status": item.status,
                "evidence_quote": item.evidence_quote,
                "owner": item.owner,
            }
            for item in requested_items
        ],
        "source_email": (
            {
                "id": str(email.id),
                "subject": email.subject,
                "sender_name": email.sender_name,
                "sender_email": email.sender_email,
                "received_at": email.received_at,
                "body_text": email.body_text,
                "body_html": email.body_html,
                "processing_state": email.processing_state,
                "current_graph_folder_id": email.current_graph_folder_id,
                "immutable_graph_message_id": email.graph_message_id,
            }
            if email
            else None
        ),
        "reviewed_classification": (
            {
                "id": str(classification.id),
                "version": classification.version,
                "vendor": classification.vendor,
                "email_type": classification.email_type,
                "states": classification.states,
                "summary": classification.summary,
                "proposed_action": classification.proposed_action,
                "review_status": classification.review_status,
                "reviewed_by_actor": classification.reviewed_by_actor,
                "reviewed_at": classification.reviewed_at,
            }
            if classification
            else None
        ),
        "approvals": [
            {
                "id": str(approval.id),
                "decision": approval.decision,
                "approver_actor": approval.approver_actor,
                "approval_snapshot_sha256": approval.approval_snapshot_sha256,
                "approval_notes": approval.approval_notes,
                "approved_at": approval.approved_at,
                "created_at": approval.created_at,
                "invalidated_at": approval.invalidated_at,
                "invalidation_reason": approval.invalidation_reason,
            }
            for approval in approvals
        ],
        "send_attempts": [
            {
                "id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "status": attempt.status,
                "http_status": attempt.http_status,
                "started_at": attempt.started_at,
                "accepted_at": attempt.accepted_at,
                "sent_copy_verified_at": attempt.sent_copy_verified_at,
                "sent_graph_message_id": attempt.sent_graph_message_id,
                "error_code": attempt.error_code,
            }
            for attempt in sends
        ],
        "move_attempts": [
            {
                "id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "status": attempt.status,
                "destination_folder_name": attempt.destination_folder_name,
                "destination_folder_id": attempt.destination_folder_id,
                "returned_graph_message_id": attempt.returned_graph_message_id,
                "returned_parent_folder_id": attempt.returned_parent_folder_id,
                "started_at": attempt.started_at,
                "verified_at": attempt.verified_at,
                "error_code": attempt.error_code,
            }
            for attempt in moves
        ],
        "completion": (
            {
                "id": str(completion.id),
                "completion_type": completion.completion_type,
                "communication_status": completion.communication_status,
                "task_status_at_completion": completion.task_status_at_completion,
                "destination_folder_name": completion.destination_folder_name,
                "final_graph_message_id": completion.final_graph_message_id,
                "completed_at": completion.completed_at,
            }
            if completion
            else None
        ),
    }


@router.post("/licensing-tasks/{task_id}/response-plan", status_code=201)
async def create_plan(
    task_id: uuid.UUID,
    body: ResponsePlanCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: Reviewer,
) -> dict[str, Any]:
    if not settings.communications_enabled:
        raise StateConflictError("Controlled communications are disabled.")
    plan = await ResponsePlanService(session).create(
        task_id,
        response_type=body.response_type,
        recipient_mode=body.recipient_mode,
        template_version_id=body.template_version_id,
        actor=actor,
        commit=False,
    )
    if not plan.response_required:
        await CommunicationJobRepository(session).enqueue(
            job_type=CommunicationJobType.MOVE_SOURCE_MESSAGE,
            idempotency_key=f"no-response-route:{plan.id}",
            email_id=plan.email_id,
            task_id=plan.task_id,
            priority=30,
            max_attempts=settings.communication_move_job_max_attempts,
        )
    await session.commit()
    return _plan(plan)


@router.get("/licensing-tasks/{task_id}/response-plan")
async def get_plan(task_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    row = await session.scalar(select(ResponsePlan).where(ResponsePlan.task_id == task_id))
    if row is None:
        raise NotFoundError("Response plan does not exist.")
    moves = list(
        await session.scalars(
            select(MessageMoveAttempt)
            .where(MessageMoveAttempt.email_id == row.email_id)
            .order_by(MessageMoveAttempt.attempt_number)
        )
    )
    completion = await session.scalar(
        select(WorkflowCompletionRecord).where(WorkflowCompletionRecord.email_id == row.email_id)
    )
    return _plan(row) | {
        "move_attempts": [
            {
                "id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "status": attempt.status,
                "destination_folder_name": attempt.destination_folder_name,
                "destination_folder_id": attempt.destination_folder_id,
                "returned_graph_message_id": attempt.returned_graph_message_id,
                "returned_parent_folder_id": attempt.returned_parent_folder_id,
                "started_at": attempt.started_at,
                "verified_at": attempt.verified_at,
                "error_code": attempt.error_code,
            }
            for attempt in moves
        ],
        "completion": (
            {
                "id": str(completion.id),
                "completion_type": completion.completion_type,
                "communication_status": completion.communication_status,
                "task_status_at_completion": completion.task_status_at_completion,
                "destination_folder_name": completion.destination_folder_name,
                "final_graph_message_id": completion.final_graph_message_id,
                "completed_at": completion.completed_at,
            }
            if completion
            else None
        ),
    }


@router.patch("/response-plans/{plan_id}")
async def patch_plan(
    plan_id: uuid.UUID,
    body: ResponsePlanPatch,
    session: SessionDep,
    settings: SettingsDep,
    actor: Reviewer,
) -> dict[str, Any]:
    plan = await session.get(ResponsePlan, plan_id)
    if plan is None:
        raise NotFoundError("Response plan does not exist.")
    next_recipient_mode = body.recipient_mode or plan.proposed_recipient_mode
    try:
        next_recipient_mode = RecipientMode(next_recipient_mode)
    except ValueError:
        raise StateConflictError("Recipient mode is invalid.") from None
    next_reply_all_reviewed = (
        body.reply_all_reviewed if body.reply_all_reviewed is not None else plan.reply_all_reviewed
    )
    if next_recipient_mode == RecipientMode.REPLY_ALL and (
        not settings.communication_reply_all_enabled or not next_reply_all_reviewed
    ):
        raise StateConflictError("Reply-all requires explicit reviewed-recipient approval.")
    if body.bcc_authorized is True and (
        not has_role(actor.roles, Role.MANAGER) or not body.bcc_authorization_reason
    ):
        raise StateConflictError("BCC requires Manager authorization and a reason.")
    destination_change = (
        body.destination_folder_name is not None or body.destination_folder_id is not None
    )
    if destination_change:
        if (
            not has_role(actor.roles, Role.MANAGER)
            or not body.destination_folder_name
            or not body.destination_folder_id
            or not body.destination_override_reason
        ):
            raise StateConflictError(
                "A destination override requires Manager authority, "
                "a verified folder, and a reason."
            )
        email = await session.get(Email, plan.email_id)
        folder = (
            await session.scalar(
                select(MailboxFolder).where(
                    MailboxFolder.mailbox_id == email.mailbox_id,
                    MailboxFolder.graph_folder_id == body.destination_folder_id,
                    MailboxFolder.display_name == body.destination_folder_name,
                )
            )
            if email
            else None
        )
        task = await session.get(LicensingTask, plan.task_id)
        if folder is None or task is None:
            raise StateConflictError("The destination folder is not verified for this mailbox.")
        before_destination = {
            "destination_folder_id": task.destination_folder_id,
            "destination_folder_name": task.destination_folder_name,
        }
        task.destination_folder_id = folder.graph_folder_id
        task.destination_folder_name = folder.display_name
        plan.suggested_destination_folder_name = folder.display_name
        add_communication_audit(
            session,
            actor=actor,
            entity_type="response_plan",
            entity_id=plan.id,
            action="destination_folder_overridden",
            before=before_destination,
            after={
                "destination_folder_id": folder.graph_folder_id,
                "destination_folder_name": folder.display_name,
            },
            metadata={"reason": body.destination_override_reason},
        )
    draft = await session.scalar(
        select(OutboundDraft).where(OutboundDraft.response_plan_id == plan.id).with_for_update()
    )
    if draft and draft.draft_status in {
        CommunicationDraftStatus.SEND_QUEUED,
        CommunicationDraftStatus.SENDING,
        CommunicationDraftStatus.SEND_ACCEPTED,
        CommunicationDraftStatus.SEND_AMBIGUOUS,
        CommunicationDraftStatus.SENT_COPY_VERIFIED,
    }:
        raise StateConflictError("A response plan cannot change after send processing begins.")
    if draft and (
        body.expected_draft_revision != draft.local_revision
        or body.expected_graph_change_key != draft.graph_change_key
        or body.expected_graph_etag != draft.graph_etag
    ):
        raise StateConflictError(
            "Draft changed before the response-plan mutation.",
            details={"current_revision": draft.local_revision},
        )
    for field, value in body.model_dump(
        exclude_none=True,
        exclude={
            "expected_draft_revision",
            "expected_graph_change_key",
            "expected_graph_etag",
            "destination_folder_name",
            "destination_folder_id",
            "destination_override_reason",
        },
    ).items():
        target = {
            "recipient_mode": "proposed_recipient_mode",
        }.get(field, field)
        setattr(plan, target, value)
    if draft:
        await invalidate_approval(session, draft, "response plan changed")
        draft.draft_status = CommunicationDraftStatus.CHANGES_REQUESTED
    await session.commit()
    return _plan(plan)


@router.post("/response-plans/{plan_id}/drafts", status_code=201)
async def create_draft(
    plan_id: uuid.UUID, body: DraftCreate, session: SessionDep, actor: Reviewer
) -> dict[str, Any]:
    return await _draft(
        session,
        await DraftGenerationService(session).generate(plan_id, values=body.values, actor=actor),
    )


@router.get("/outbound-drafts")
async def list_drafts(
    session: SessionDep,
    actor: ActorDep,
    status: str | None = None,
    task_id: uuid.UUID | None = None,
    email_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    stmt = select(OutboundDraft)
    if status:
        stmt = stmt.where(OutboundDraft.draft_status == status)
    if task_id:
        stmt = stmt.where(OutboundDraft.task_id == task_id)
    if email_id:
        stmt = stmt.where(OutboundDraft.email_id == email_id)
    return [
        await _draft(session, row)
        for row in await session.scalars(stmt.order_by(OutboundDraft.updated_at.desc()))
    ]


@router.get("/outbound-drafts/{draft_id}")
async def get_draft(draft_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    row = await session.get(OutboundDraft, draft_id)
    if row is None:
        raise NotFoundError("Draft does not exist.")
    return await _draft(session, row)


@router.patch("/outbound-drafts/{draft_id}")
async def patch_draft(
    draft_id: uuid.UUID,
    body: DraftPatch,
    session: SessionDep,
    settings: SettingsDep,
    graph: GraphClientDep,
    actor: Reviewer,
) -> dict[str, Any]:
    existing = await session.get(OutboundDraft, draft_id)
    if existing is None:
        raise NotFoundError("Draft does not exist.")
    if existing.graph_draft_message_id:
        _, changed = await GraphDraftService(session, settings, graph).sync(draft_id, actor)
        if changed:
            raise StateConflictError("Outlook changed the draft; review the imported revision.")
    row = await DraftGenerationService(session).edit(
        draft_id,
        expected_revision=body.expected_revision,
        expected_graph_change_key=body.expected_graph_change_key,
        expected_graph_etag=body.expected_graph_etag,
        subject=body.subject,
        body_text=body.body_text,
        body_html=body.body_html,
        to_recipients=[item.model_dump() for item in body.to_recipients],
        cc_recipients=[item.model_dump() for item in body.cc_recipients],
        bcc_recipients=[item.model_dump() for item in body.bcc_recipients],
        reason=body.change_reason,
        actor=actor,
    )
    if row.graph_draft_message_id:
        row = await GraphDraftService(session, settings, graph).push_local(draft_id, actor)
    return await _draft(session, row)


@router.post("/outbound-drafts/{draft_id}/ai-suggestion")
async def apply_ai_suggestion(
    draft_id: uuid.UUID,
    body: DraftMutationExpectation,
    session: SessionDep,
    settings: SettingsDep,
    graph: GraphClientDep,
    actor: Reviewer,
) -> dict[str, Any]:
    current = await session.get(OutboundDraft, draft_id)
    if current is None:
        raise NotFoundError("Draft does not exist.")
    if current.local_revision != body.expected_revision or (
        current.graph_draft_message_id
        and (
            current.graph_change_key != body.expected_graph_change_key
            or current.graph_etag != body.expected_graph_etag
        )
    ):
        raise StateConflictError(
            "Draft or Graph identity changed before suggestion generation.",
            details={"current_revision": current.local_revision},
        )
    if current.graph_draft_message_id:
        _, changed = await GraphDraftService(session, settings, graph).sync(draft_id, actor)
        if changed:
            raise StateConflictError("Outlook changed the draft; review the imported revision.")
    provider = OpenAIResponseSuggestionProvider(settings)
    try:
        row = await ResponseSuggestionService(session, settings, provider).suggest_and_apply(
            draft_id,
            expected_revision=body.expected_revision,
            actor=actor,
        )
    finally:
        await provider.aclose()
    if row.graph_draft_message_id:
        row = await GraphDraftService(session, settings, graph).push_local(draft_id, actor)
    return await _draft(session, row)


@router.get("/outbound-drafts/{draft_id}/versions")
async def versions(
    draft_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[dict[str, Any]]:
    rows = list(
        await session.scalars(
            select(OutboundDraftVersion)
            .where(OutboundDraftVersion.outbound_draft_id == draft_id)
            .order_by(OutboundDraftVersion.revision.desc())
        )
    )
    return [
        {
            "id": str(row.id),
            "revision": row.revision,
            "subject": row.subject,
            "body_text": row.body_text,
            "body_html": row.body_html,
            "to_recipients": row.to_recipients,
            "cc_recipients": row.cc_recipients,
            "bcc_recipients": row.bcc_recipients,
            "attachment_manifest": row.attachment_manifest,
            "body_sha256": row.body_sha256,
            "recipient_set_sha256": row.recipient_set_sha256,
            "attachment_set_sha256": row.attachment_set_sha256,
            "snapshot_sha256": row.snapshot_sha256,
            "change_reason": row.change_reason,
            "created_by_actor": row.created_by_actor,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/outbound-drafts/{draft_id}/graph-draft")
async def graph_draft(
    draft_id: uuid.UUID,
    body: DraftMutationExpectation,
    session: SessionDep,
    settings: SettingsDep,
    graph: GraphClientDep,
    actor: Reviewer,
) -> dict[str, Any]:
    current = await session.get(OutboundDraft, draft_id)
    if current is None:
        raise NotFoundError("Draft does not exist.")
    if current.local_revision != body.expected_revision:
        raise StateConflictError(
            "Draft revision changed.", details={"current_revision": current.local_revision}
        )
    if current.graph_draft_message_id and (
        current.graph_change_key != body.expected_graph_change_key
        or current.graph_etag != body.expected_graph_etag
    ):
        raise StateConflictError("Graph draft changed; reconcile before continuing.")
    return await _draft(
        session, await GraphDraftService(session, settings, graph).create(draft_id, actor)
    )


@router.post("/outbound-drafts/{draft_id}/graph-sync")
async def graph_sync(
    draft_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    graph: GraphClientDep,
    actor: Reviewer,
) -> dict[str, Any]:
    row, changed = await GraphDraftService(session, settings, graph).sync(draft_id, actor)
    return {"draft": await _draft(session, row), "external_change_detected": changed}


@router.post("/outbound-drafts/{draft_id}/reconcile")
async def graph_reconcile(
    draft_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    graph: GraphClientDep,
    actor: Reviewer,
) -> dict[str, Any]:
    row, changed = await GraphDraftService(session, settings, graph).reconcile(draft_id, actor)
    return {"draft": await _draft(session, row), "external_change_detected": changed}


@router.post("/outbound-drafts/{draft_id}/attachments", status_code=201)
async def select_attachment(
    draft_id: uuid.UUID,
    body: AttachmentSelect,
    session: SessionDep,
    settings: SettingsDep,
    actor: Reviewer,
) -> dict[str, Any]:
    row = await DraftAttachmentService(session, settings).select(
        draft_id,
        body.document_id,
        body.document_version_id,
        actor,
        expected_revision=body.expected_revision,
        expected_graph_change_key=body.expected_graph_change_key,
        expected_graph_etag=body.expected_graph_etag,
    )
    return {"id": str(row.id), "filename": row.filename, "status": row.status}


@router.delete("/outbound-drafts/{draft_id}/attachments/{attachment_id}", status_code=204)
async def remove_attachment(
    draft_id: uuid.UUID,
    attachment_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    graph: GraphClientDep,
    actor: Reviewer,
    expected_revision: int,
    expected_graph_change_key: str | None = None,
    expected_graph_etag: str | None = None,
) -> Response:
    removed_from_graph = await GraphDraftAttachmentService(
        session, settings, graph
    ).remove_uploaded(
        draft_id,
        attachment_id,
        expected_revision=expected_revision,
        expected_graph_change_key=expected_graph_change_key,
        expected_graph_etag=expected_graph_etag,
        actor=actor,
    )
    await DraftAttachmentService(session, settings).remove(
        draft_id,
        attachment_id,
        actor,
        expected_revision=expected_revision,
        expected_graph_change_key=expected_graph_change_key,
        expected_graph_etag=expected_graph_etag,
    )
    if removed_from_graph:
        await GraphDraftService(session, settings, graph).sync(
            draft_id,
            actor,
            allow_expected_transport_metadata_change=True,
        )
    return Response(status_code=204)


@router.post("/outbound-drafts/{draft_id}/submit-approval")
async def submit_approval(
    draft_id: uuid.UUID,
    body: DraftMutationExpectation,
    session: SessionDep,
    settings: SettingsDep,
    graph: GraphClientDep,
    actor: Reviewer,
) -> dict[str, Any]:
    current = await session.get(OutboundDraft, draft_id)
    if current is None:
        raise NotFoundError("Draft does not exist.")
    if current.local_revision != body.expected_revision or (
        current.graph_draft_message_id
        and (
            current.graph_change_key != body.expected_graph_change_key
            or current.graph_etag != body.expected_graph_etag
        )
    ):
        raise StateConflictError(
            "Draft or Graph identity changed before approval submission.",
            details={"current_revision": current.local_revision},
        )
    _, changed = await GraphDraftService(session, settings, graph).sync(draft_id, actor)
    if changed:
        raise StateConflictError("Outlook-side changes require another content review.")
    uploaded = await GraphDraftAttachmentService(session, settings, graph).upload_pending(
        draft_id, actor
    )
    if uploaded:
        _, changed_after_upload = await GraphDraftService(session, settings, graph).sync(
            draft_id,
            actor,
            allow_expected_transport_metadata_change=True,
        )
        if changed_after_upload:
            raise StateConflictError(
                "Graph draft changed while attachments were being synchronized."
            )
    current = await session.get(OutboundDraft, draft_id)
    if current is None:
        raise NotFoundError("Draft does not exist.")
    return await _draft(
        session,
        await DraftReviewService(session, settings).submit(
            draft_id,
            actor,
            expected_revision=current.local_revision,
            expected_graph_change_key=current.graph_change_key,
            expected_graph_etag=current.graph_etag,
        ),
    )


@router.post("/outbound-drafts/{draft_id}/request-changes")
async def request_changes(
    draft_id: uuid.UUID,
    body: ReviewReason,
    session: SessionDep,
    settings: SettingsDep,
    actor: Reviewer,
) -> dict[str, Any]:
    return await _draft(
        session,
        await DraftReviewService(session, settings).request_changes(
            draft_id,
            body.reason,
            actor,
            expected_revision=body.expected_revision,
            expected_graph_change_key=body.expected_graph_change_key,
            expected_graph_etag=body.expected_graph_etag,
        ),
    )


@router.post("/outbound-drafts/{draft_id}/reject")
async def reject_draft(
    draft_id: uuid.UUID,
    body: ReviewReason,
    session: SessionDep,
    settings: SettingsDep,
    actor: Reviewer,
) -> dict[str, Any]:
    return await _draft(
        session,
        await DraftReviewService(session, settings).reject(
            draft_id,
            body.reason,
            actor,
            expected_revision=body.expected_revision,
            expected_graph_change_key=body.expected_graph_change_key,
            expected_graph_etag=body.expected_graph_etag,
        ),
    )


@router.post("/outbound-drafts/{draft_id}/approve-send")
async def approve_send(
    draft_id: uuid.UUID,
    body: SendApprovalIn,
    session: SessionDep,
    settings: SettingsDep,
    graph: GraphClientDep,
    actor: Sender,
) -> dict[str, Any]:
    _, changed = await GraphDraftService(session, settings, graph).sync(draft_id, actor)
    if changed:
        raise StateConflictError("Graph draft changed before approval.")
    row = await SendApprovalService(session, settings).approve(
        draft_id,
        expected_revision=body.expected_revision,
        expected_snapshot_sha256=body.expected_approval_snapshot_sha256,
        expected_graph_draft_id=body.expected_graph_draft_id,
        expected_graph_change_key=body.expected_graph_change_key,
        expected_graph_etag=body.expected_graph_etag,
        notes=body.approval_notes,
        actor=actor,
    )
    return {
        "id": str(row.id),
        "decision": row.decision,
        "approved_at": row.approved_at,
        "snapshot_sha256": row.approval_snapshot_sha256,
    }


@router.post("/outbound-drafts/{draft_id}/send-request-changes")
async def send_request_changes(
    draft_id: uuid.UUID,
    body: ReviewReason,
    session: SessionDep,
    settings: SettingsDep,
    actor: Sender,
) -> dict[str, Any]:
    row = await SendApprovalService(session, settings).decline(
        draft_id,
        decision=ApprovalDecision.CHANGES_REQUESTED,
        reason=body.reason,
        expected_revision=body.expected_revision,
        expected_graph_change_key=body.expected_graph_change_key,
        expected_graph_etag=body.expected_graph_etag,
        actor=actor,
    )
    return await _draft(session, row)


@router.post("/outbound-drafts/{draft_id}/reject-send")
async def reject_send(
    draft_id: uuid.UUID,
    body: ReviewReason,
    session: SessionDep,
    settings: SettingsDep,
    actor: Sender,
) -> dict[str, Any]:
    row = await SendApprovalService(session, settings).decline(
        draft_id,
        decision=ApprovalDecision.REJECTED,
        reason=body.reason,
        expected_revision=body.expected_revision,
        expected_graph_change_key=body.expected_graph_change_key,
        expected_graph_etag=body.expected_graph_etag,
        actor=actor,
    )
    return await _draft(session, row)


@router.post("/outbound-drafts/{draft_id}/cancel-send")
async def cancel_unsent_send(
    draft_id: uuid.UUID,
    body: ReviewReason,
    session: SessionDep,
    settings: SettingsDep,
    actor: Sender,
) -> dict[str, Any]:
    row = await SendApprovalService(session, settings).cancel_unsent(
        draft_id,
        reason=body.reason,
        expected_revision=body.expected_revision,
        expected_graph_change_key=body.expected_graph_change_key,
        expected_graph_etag=body.expected_graph_etag,
        actor=actor,
    )
    return await _draft(session, row)


@router.post("/outbound-drafts/{draft_id}/invalidate-approval")
async def invalidate_send_approval(
    draft_id: uuid.UUID,
    body: ReviewReason,
    session: SessionDep,
    settings: SettingsDep,
    actor: Sender,
) -> dict[str, Any]:
    return await _draft(
        session,
        await SendApprovalService(session, settings).invalidate(draft_id, body.reason, actor),
    )


@router.post("/outbound-drafts/{draft_id}/send", status_code=202)
async def enqueue_send(
    draft_id: uuid.UUID,
    body: SendEnqueueIn,
    session: SessionDep,
    settings: SettingsDep,
    actor: Sender,
) -> dict[str, Any]:
    job_id, created = await CommunicationEnqueueService(session, settings).send(
        draft_id,
        idempotency_key=body.idempotency_key,
        explicit_confirmation=body.explicit_confirmation,
        actor=actor,
    )
    return {"job_id": str(job_id), "created": created, "status": "SEND_QUEUED"}


@router.get("/outbound-drafts/{draft_id}/send-attempts")
async def send_attempts(
    draft_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[dict[str, Any]]:
    rows = list(
        await session.scalars(
            select(OutboundSendAttempt)
            .where(OutboundSendAttempt.outbound_draft_id == draft_id)
            .order_by(OutboundSendAttempt.attempt_number)
        )
    )
    return [
        {
            "id": str(row.id),
            "attempt_number": row.attempt_number,
            "status": row.status,
            "http_status": row.http_status,
            "accepted_at": row.accepted_at,
            "sent_copy_verified_at": row.sent_copy_verified_at,
            "delivery_status": "UNKNOWN",
        }
        for row in rows
    ]


@router.post("/outbound-drafts/{draft_id}/reconcile-send", status_code=202)
async def reconcile_send(
    draft_id: uuid.UUID, session: SessionDep, settings: SettingsDep, actor: Manager
) -> dict[str, Any]:
    job_id, created = await CommunicationEnqueueService(session, settings).reconcile_send(draft_id)
    return {"job_id": str(job_id), "created": created}


@router.post("/emails/{email_id}/move-job", status_code=202)
async def enqueue_move(
    email_id: uuid.UUID, session: SessionDep, settings: SettingsDep, actor: Manager
) -> dict[str, Any]:
    job, created = await CommunicationJobRepository(session).enqueue(
        job_type=CommunicationJobType.MOVE_SOURCE_MESSAGE,
        idempotency_key=f"manual-move:{email_id}",
        email_id=email_id,
        priority=30,
        max_attempts=settings.communication_move_job_max_attempts,
    )
    await session.commit()
    return {"job_id": str(job.id), "created": created}


@router.get("/emails/{email_id}/move-attempts")
async def move_attempts(
    email_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[dict[str, Any]]:
    rows = list(
        await session.scalars(
            select(MessageMoveAttempt)
            .where(MessageMoveAttempt.email_id == email_id)
            .order_by(MessageMoveAttempt.attempt_number)
        )
    )
    return [
        {
            "id": str(row.id),
            "status": row.status,
            "destination_folder_name": row.destination_folder_name,
            "returned_graph_message_id": row.returned_graph_message_id,
            "verified_at": row.verified_at,
        }
        for row in rows
    ]


@router.post("/emails/{email_id}/complete-workflow")
async def complete_workflow(
    email_id: uuid.UUID, session: SessionDep, actor: Manager
) -> dict[str, Any]:
    row = await WorkflowCompletionService(session).complete(email_id, actor)
    return {
        "id": str(row.id),
        "communication_status": row.communication_status,
        "task_status_at_completion": row.task_status_at_completion,
    }


@router.get("/communication-templates")
async def templates(session: SessionDep, actor: ActorDep) -> list[dict[str, Any]]:
    rows = list(await session.scalars(select(ResponseTemplate).order_by(ResponseTemplate.name)))
    result = []
    for row in rows:
        active = await session.scalar(
            select(ResponseTemplateVersion).where(
                ResponseTemplateVersion.response_template_id == row.id,
                ResponseTemplateVersion.status == "ACTIVE",
            )
        )
        result.append(
            {
                "id": str(row.id),
                "template_key": row.template_key,
                "name": row.name,
                "response_type": row.response_type,
                "is_active": row.is_active,
                "active_version_id": str(active.id) if active else None,
            }
        )
    return result


@router.get("/communication-templates/{template_id}")
async def template_detail(
    template_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    row = await session.get(ResponseTemplate, template_id)
    if row is None:
        raise NotFoundError("Communication template does not exist.")
    versions = list(
        await session.scalars(
            select(ResponseTemplateVersion)
            .where(ResponseTemplateVersion.response_template_id == row.id)
            .order_by(ResponseTemplateVersion.version.desc())
        )
    )
    return {
        "template": {
            "id": str(row.id),
            "template_key": row.template_key,
            "name": row.name,
            "response_type": row.response_type,
        },
        "versions": [
            {
                "id": str(v.id),
                "version": v.version,
                "status": v.status,
                "template_sha256": v.template_sha256,
            }
            for v in versions
        ],
    }


@router.post("/admin/communication-templates", status_code=201)
async def create_template(
    body: TemplateCreate, session: SessionDep, actor: Admin
) -> dict[str, Any]:
    try:
        ResponseType(body.response_type)
    except ValueError:
        raise StateConflictError("Communication template response type is invalid.") from None
    row = ResponseTemplate(**body.model_dump(), is_active=True)
    session.add(row)
    await session.flush()
    add_communication_audit(
        session,
        actor=actor,
        entity_type="response_template",
        entity_id=row.id,
        action="response_template_created",
        after={"template_key": row.template_key, "response_type": row.response_type},
    )
    await session.commit()
    return {"id": str(row.id), "template_key": row.template_key}


@router.post("/admin/communication-templates/{template_id}/versions", status_code=201)
async def create_template_version(
    template_id: uuid.UUID, body: TemplateVersionCreate, session: SessionDep, actor: Admin
) -> dict[str, Any]:
    row = await ResponseTemplateService(session).create_version(
        template_id,
        subject=body.subject_template,
        body=body.text_body_template,
        html_body=body.html_body_template,
        allowed_variables=body.allowed_variables,
        actor=actor,
    )
    return {"id": str(row.id), "version": row.version, "status": row.status}


@router.post("/admin/communication-templates/{template_id}/versions/{version_id}/activate")
async def activate_template(
    template_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, actor: Admin
) -> dict[str, Any]:
    candidate = await session.get(ResponseTemplateVersion, version_id)
    if candidate is None or candidate.response_template_id != template_id:
        raise NotFoundError("Template version does not belong to this template.")
    row = await ResponseTemplateService(session).activate(version_id, actor)
    return {"id": str(row.id), "status": row.status, "activated_at": row.activated_at}


def _validate_recipient_policy_conditions(rule_type: str, conditions: dict[str, Any]) -> None:
    list_rules = {
        "BLOCKED_DOMAIN",
        "BLOCKED_ADDRESS",
        "ALLOWED_DOMAIN",
        "ALLOWED_ADDRESS",
        "INTERNAL_ONLY",
    }
    if rule_type in list_rules:
        values = conditions.get("values", conditions.get("domains"))
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)
        ):
            raise StateConflictError("Recipient policy requires a non-empty string value list.")
    if rule_type == "MAX_RECIPIENTS":
        maximum = conditions.get("maximum", conditions.get("max"))
        if not isinstance(maximum, int) or maximum < 1:
            raise StateConflictError("MAX_RECIPIENTS requires a positive integer maximum.")


@router.get("/admin/recipient-policies")
async def recipient_policies(session: SessionDep, actor: Admin) -> list[dict[str, Any]]:
    rows = list(
        await session.scalars(
            select(RecipientPolicyRule).order_by(
                RecipientPolicyRule.priority, RecipientPolicyRule.rule_key
            )
        )
    )
    return [
        {
            "id": str(row.id),
            "rule_key": row.rule_key,
            "rule_type": row.rule_type,
            "priority": row.priority,
            "conditions": row.conditions,
            "action": row.action,
            "enabled": row.enabled,
            "reason": row.reason,
            "created_by_actor": row.created_by_actor,
            "approved_by_actor": row.approved_by_actor,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.post("/admin/recipient-policies", status_code=201)
async def create_recipient_policy(
    body: RecipientPolicyCreate, session: SessionDep, actor: Admin
) -> dict[str, Any]:
    _validate_recipient_policy_conditions(body.rule_type, body.conditions)
    row = RecipientPolicyRule(
        **body.model_dump(),
        created_by_actor=actor.actor_id,
        approved_by_actor=actor.actor_id,
    )
    session.add(row)
    await session.flush()
    add_communication_audit(
        session,
        actor=actor,
        entity_type="recipient_policy_rule",
        entity_id=row.id,
        action="recipient_policy_created",
        after={
            "rule_key": row.rule_key,
            "rule_type": row.rule_type,
            "action": row.action,
            "enabled": row.enabled,
        },
    )
    await session.commit()
    return {"id": str(row.id), "rule_key": row.rule_key, "enabled": row.enabled}


@router.patch("/admin/recipient-policies/{policy_id}")
async def patch_recipient_policy(
    policy_id: uuid.UUID,
    body: RecipientPolicyPatch,
    session: SessionDep,
    actor: Admin,
) -> dict[str, Any]:
    row = await session.scalar(
        select(RecipientPolicyRule).where(RecipientPolicyRule.id == policy_id).with_for_update()
    )
    if row is None:
        raise NotFoundError("Recipient policy does not exist.")
    next_conditions = body.conditions if body.conditions is not None else row.conditions
    _validate_recipient_policy_conditions(row.rule_type, next_conditions)
    before = {
        "priority": row.priority,
        "action": row.action,
        "enabled": row.enabled,
    }
    if body.priority is not None:
        row.priority = body.priority
    if body.conditions is not None:
        row.conditions = body.conditions
    if body.action is not None:
        row.action = body.action
    if body.enabled is not None:
        row.enabled = body.enabled
    row.reason = body.reason
    row.approved_by_actor = actor.actor_id
    add_communication_audit(
        session,
        actor=actor,
        entity_type="recipient_policy_rule",
        entity_id=row.id,
        action="recipient_policy_updated",
        before=before,
        after={
            "priority": row.priority,
            "action": row.action,
            "enabled": row.enabled,
        },
        metadata={"reason": body.reason},
    )
    await session.commit()
    return {"id": str(row.id), "rule_key": row.rule_key, "enabled": row.enabled}


@router.get("/communications/dashboard")
async def communications_dashboard(session: SessionDep, actor: ActorDep) -> dict[str, int]:
    pending = await session.scalar(
        select(func.count(OutboundDraft.id)).where(
            OutboundDraft.draft_status == "PENDING_SEND_APPROVAL"
        )
    )
    ambiguous = await session.scalar(
        select(func.count(OutboundDraft.id)).where(OutboundDraft.draft_status == "SEND_AMBIGUOUS")
    )
    completed = await session.scalar(select(func.count(WorkflowCompletionRecord.id)))
    return {
        "pending_send_approval": int(pending or 0),
        "send_ambiguous": int(ambiguous or 0),
        "workflows_completed": int(completed or 0),
    }


@router.get("/communications/capabilities")
async def communication_capabilities(settings: SettingsDep, actor: ActorDep) -> dict[str, Any]:
    """Expose non-secret feature posture for portal controls."""
    return {
        "communications_enabled": settings.communications_enabled,
        "graph_draft_creation_enabled": settings.graph_draft_creation_enabled,
        "response_ai_drafting_enabled": settings.response_ai_drafting_enabled,
        "attachments_enabled": settings.communication_attachments_enabled,
        "large_attachments_enabled": (
            settings.communication_large_attachments_enabled
            and settings.communication_shared_mailbox_large_attachment_accepted
        ),
        "reply_all_enabled": settings.communication_reply_all_enabled,
        "bcc_enabled": settings.communication_bcc_enabled,
        "two_person_send_approval": settings.communication_require_two_person_approval,
        "separate_send_approver": (
            settings.communication_require_separate_send_approver
            or not settings.communication_allow_self_approval
        ),
        "accepted_is_delivery": False,
    }


@router.get("/integrations/graph/mail-send-status")
async def mail_send_status(settings: SettingsDep, actor: Admin) -> dict[str, Any]:
    return {
        "communications_enabled": settings.communications_enabled,
        "graph_draft_creation_enabled": settings.graph_draft_creation_enabled,
        "graph_send_enabled": settings.graph_send_enabled,
        "graph_message_move_enabled": settings.graph_message_move_enabled,
        "expected_mailbox_configured": bool(settings.graph_expected_mailbox_address),
        "accepted_is_delivery": False,
    }

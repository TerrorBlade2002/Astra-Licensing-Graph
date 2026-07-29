"""Local deterministic draft generation and revisioning; no Graph call occurs here."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.communications.audit import add_communication_audit
from app.communications.enums import CommunicationDraftStatus, ReadinessStatus, RecipientMode
from app.communications.readiness import ResponseReadinessService
from app.communications.rendering import ResponseTemplateRenderer
from app.communications.signatures import apply_signature
from app.communications.snapshots import create_version, invalidate_approval
from app.communications.validation import validate_draft_content
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import (
    COMMUNICATION_DRAFT_VALIDATION_FAILURES_TOTAL,
    COMMUNICATION_DRAFTS_CREATED_TOTAL,
)
from app.models import (
    Classification,
    Email,
    LicensingTask,
    Mailbox,
    OutboundDraft,
    OutboundDraftAttachment,
    ResponsePlan,
    ResponseTemplateVersion,
    TaskEvent,
    TaskRequestedItem,
)
from app.models.mixins import utcnow


class DraftGenerationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def generate(
        self, plan_id: uuid.UUID, *, values: dict[str, object], actor: CurrentActor
    ) -> OutboundDraft:
        plan = await self.session.get(ResponsePlan, plan_id)
        if plan is None or not plan.response_required:
            raise StateConflictError("This response plan does not require a draft.")
        task = await self.session.get(LicensingTask, plan.task_id)
        email = await self.session.get(Email, plan.email_id)
        version = (
            await self.session.get(ResponseTemplateVersion, plan.selected_template_version_id)
            if plan.selected_template_version_id
            else None
        )
        if task is None or email is None or version is None or version.status != "ACTIVE":
            raise NotFoundError("Active response template or source evidence is missing.")
        classification = await self.session.get(Classification, plan.classification_id)
        mailbox = await self.session.get(Mailbox, email.mailbox_id)
        requested_items = list(
            await self.session.scalars(
                select(TaskRequestedItem)
                .where(TaskRequestedItem.task_id == task.id)
                .order_by(TaskRequestedItem.sort_order)
            )
        )
        requested_statuses = [item.status for item in requested_items]
        readiness = ResponseReadinessService().evaluate(
            response_type=plan.response_type,
            requested_item_statuses=requested_statuses,
            recipient_count=(0 if plan.proposed_recipient_mode == RecipientMode.NONE else 1),
            task_status=task.status,
            task_owner=task.assigned_to,
            destination_folder_id=task.destination_folder_id,
            response_deadline=task.due_date,
            check_task_context=True,
        )
        plan.readiness_status = readiness.status
        plan.readiness_blockers = list(readiness.blockers)
        if readiness.status in {ReadinessStatus.NOT_READY, ReadinessStatus.BLOCKED}:
            await self.session.commit()
            raise StateConflictError(
                "Response plan is not ready for drafting.",
                details={"blockers": list(readiness.blockers)},
            )
        controlled_values: dict[str, object] = {
            "vendor_name": (
                task.vendor
                or (classification.vendor if classification else None)
                or email.sender_name
                or "Correspondent"
            ),
            "jurisdiction": ", ".join(classification.states) if classification else "",
            "license_type": (", ".join(classification.license_types) if classification else ""),
            "license_number": (", ".join(classification.license_numbers) if classification else ""),
            "requested_items": "\n".join(
                f"- {item.item_text}"
                for item in requested_items
                if item.status in {"VERIFIED", "NOT_APPLICABLE"}
            ),
            "due_date": task.due_date.isoformat() if task.due_date else "",
            "task_owner_name": task.assigned_to or "",
            "licensing_mailbox": mailbox.address if mailbox else "",
            "approved_document_list": "",
            "legal_entity": "",
            "response_reference": email.subject or task.title,
        }
        unknown_inputs = set(values) - set(version.allowed_variables)
        if unknown_inputs:
            raise StateConflictError(
                "Draft values contain non-allowlisted template fields.",
                details={"fields": sorted(unknown_inputs)},
            )
        for key, supplied in values.items():
            authoritative = controlled_values.get(key)
            if authoritative not in {None, ""} and str(supplied) != str(authoritative):
                raise StateConflictError(
                    "Portal values cannot override reviewed application data.",
                    details={"field": key},
                )
            controlled_values[key] = supplied
        render_values = {key: controlled_values.get(key, "") for key in version.allowed_variables}
        rendered = ResponseTemplateRenderer().render(
            subject_template=version.subject_template,
            text_template=version.text_body_template,
            html_template=version.html_body_template,
            allowed_variables=version.allowed_variables,
            values=render_values,
        )
        body = apply_signature(rendered.body_text, plan.selected_signature_key or "")
        findings = validate_draft_content(
            subject=rendered.subject,
            body_text=body,
            body_html=rendered.body_html,
            attachment_count=0,
        )
        if findings:
            COMMUNICATION_DRAFT_VALIDATION_FAILURES_TOTAL.inc()
            plan.readiness_status = ReadinessStatus.BLOCKED
            plan.readiness_blockers = findings
            await self.session.commit()
            raise StateConflictError(
                "Generated draft failed controlled validation.",
                details={"blockers": findings},
            )
        existing = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.response_plan_id == plan.id)
        )
        if existing:
            raise StateConflictError("A draft already exists for this response plan.")
        draft = OutboundDraft(
            response_plan_id=plan.id,
            task_id=task.id,
            email_id=email.id,
            mailbox_id=email.mailbox_id,
            subject=rendered.subject,
            body_text=body,
            body_html=rendered.body_html,
            to_recipients=[],
            cc_recipients=[],
            bcc_recipients=[],
            reply_to_recipients=[],
            draft_status=CommunicationDraftStatus.LOCAL_DRAFT,
            local_revision=1,
            body_sha256="",
            recipient_set_sha256="",
            attachment_set_sha256="",
            created_by_actor=actor.actor_id,
            last_edited_by_actor=actor.actor_id,
            delivery_status="NOT_APPLICABLE",
        )
        self.session.add(draft)
        await self.session.flush()
        await create_version(
            self.session, draft, actor_id=actor.actor_id, change_reason="generated", increment=False
        )
        task.communication_status = "LOCAL_DRAFT"
        self.session.add(
            TaskEvent(
                task_id=task.id,
                event_type="COMMUNICATION_DRAFT_CREATED",
                actor_id=actor.actor_id,
                event_metadata={"draft_id": str(draft.id)},
                occurred_at=utcnow(),
            )
        )
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="outbound_draft",
            entity_id=draft.id,
            action="local_draft_created",
            after={"revision": draft.local_revision, "status": draft.draft_status},
        )
        await self.session.commit()
        COMMUNICATION_DRAFTS_CREATED_TOTAL.inc()
        return draft

    async def edit(
        self,
        draft_id: uuid.UUID,
        *,
        expected_revision: int,
        expected_graph_change_key: str | None,
        expected_graph_etag: str | None,
        subject: str,
        body_text: str | None,
        body_html: str | None,
        to_recipients: list[dict[str, object]],
        cc_recipients: list[dict[str, object]],
        bcc_recipients: list[dict[str, object]],
        reason: str,
        actor: CurrentActor,
    ) -> OutboundDraft:
        draft = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.id == draft_id).with_for_update()
        )
        if draft is None:
            raise NotFoundError("Draft does not exist.")
        if draft.local_revision != expected_revision:
            raise StateConflictError(
                "Draft revision changed.", details={"current_revision": draft.local_revision}
            )
        if draft.graph_draft_message_id and (
            draft.graph_change_key != expected_graph_change_key
            or draft.graph_etag != expected_graph_etag
        ):
            raise StateConflictError("Graph draft changed; synchronize before editing.")
        if draft.draft_status in {
            CommunicationDraftStatus.SEND_QUEUED,
            CommunicationDraftStatus.SENDING,
            CommunicationDraftStatus.SEND_ACCEPTED,
            CommunicationDraftStatus.SEND_AMBIGUOUS,
            CommunicationDraftStatus.SENT_COPY_VERIFIED,
        }:
            raise StateConflictError("A sending or sent draft cannot be edited.")
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
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            attachment_count=attachment_count,
        )
        if findings:
            COMMUNICATION_DRAFT_VALIDATION_FAILURES_TOTAL.inc()
            raise StateConflictError(
                "Draft content failed controlled validation.",
                details={"blockers": findings},
            )
        prior_revision = draft.local_revision
        draft.subject, draft.body_text, draft.body_html = subject, body_text, body_html
        draft.to_recipients = to_recipients
        draft.cc_recipients = cc_recipients
        draft.bcc_recipients = bcc_recipients
        await invalidate_approval(self.session, draft, "draft content or recipients changed")
        await create_version(self.session, draft, actor_id=actor.actor_id, change_reason=reason)
        draft.draft_status = CommunicationDraftStatus.REVIEW_IN_PROGRESS
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="outbound_draft",
            entity_id=draft.id,
            action="draft_revision_created",
            before={"revision": prior_revision},
            after={"revision": draft.local_revision, "status": draft.draft_status},
        )
        await self.session.commit()
        return draft

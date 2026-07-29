"""Apply an optional provider suggestion as a normal human-reviewable revision."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.response_drafting import (
    ResponseSuggestion,
    ResponseSuggestionInput,
    ResponseSuggestionProvider,
)
from app.auth.actors import CurrentActor
from app.communications.audit import add_communication_audit
from app.communications.enums import CommunicationDraftStatus
from app.communications.snapshots import create_version, invalidate_approval
from app.communications.validation import validate_draft_content
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.models import (
    Classification,
    Document,
    OutboundDraft,
    OutboundDraftAttachment,
    ResponsePlan,
    TaskEvent,
    TaskRequestedItem,
)
from app.models.mixins import utcnow


class ResponseSuggestionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        provider: ResponseSuggestionProvider,
    ) -> None:
        self.session, self.settings, self.provider = session, settings, provider

    async def suggest_and_apply(
        self,
        draft_id: uuid.UUID,
        *,
        expected_revision: int,
        actor: CurrentActor,
    ) -> OutboundDraft:
        if not self.settings.response_ai_drafting_enabled:
            raise StateConflictError("AI response drafting is disabled.")
        draft = await self.session.get(OutboundDraft, draft_id)
        if draft is None or draft.response_plan_id is None:
            raise NotFoundError("Draft does not exist.")
        if draft.local_revision != expected_revision:
            raise StateConflictError("Draft revision changed before suggestion generation.")
        if draft.draft_status in {
            CommunicationDraftStatus.PENDING_SEND_APPROVAL,
            CommunicationDraftStatus.APPROVED_TO_SEND,
            CommunicationDraftStatus.SEND_QUEUED,
            CommunicationDraftStatus.SENDING,
            CommunicationDraftStatus.SEND_ACCEPTED,
            CommunicationDraftStatus.SEND_AMBIGUOUS,
            CommunicationDraftStatus.SENT_COPY_VERIFIED,
        }:
            raise StateConflictError(
                "AI suggestions cannot modify an approval or send-stage draft."
            )
        plan = await self.session.get(ResponsePlan, draft.response_plan_id)
        classification = (
            await self.session.get(Classification, plan.classification_id) if plan else None
        )
        items = list(
            await self.session.scalars(
                select(TaskRequestedItem).where(
                    TaskRequestedItem.task_id == draft.task_id,
                    TaskRequestedItem.status.in_(["VERIFIED", "NOT_APPLICABLE"]),
                )
            )
        )
        selected = list(
            await self.session.scalars(
                select(OutboundDraftAttachment).where(
                    OutboundDraftAttachment.outbound_draft_id == draft.id,
                    OutboundDraftAttachment.removed_at.is_(None),
                )
            )
        )
        documents: list[Document] = []
        for attachment in selected:
            document = (
                await self.session.get(Document, attachment.document_id)
                if attachment.document_id
                else None
            )
            if (
                document is not None
                and document.approval_status == "APPROVED"
                and document.lifecycle_status == "ACTIVE"
            ):
                documents.append(document)
        source_values: dict[str, str] = {
            str(item.id): json.dumps(
                {
                    "item_text": item.item_text,
                    "category": item.category,
                    "evidence_quote": item.evidence_quote,
                    "status": item.status,
                },
                default=str,
            )
            for item in items
        }
        source_values.update(
            {
                str(document.id): json.dumps(
                    {
                        "canonical_title": document.canonical_title,
                        "document_type": document.document_type,
                        "jurisdiction": document.jurisdiction,
                        "expiry_date": document.expiry_date,
                        "approval_status": document.approval_status,
                    },
                    default=str,
                )
                for document in documents
            }
        )
        if classification is not None:
            source_values[str(classification.id)] = json.dumps(
                {"summary": classification.summary},
                default=str,
            )
        provider_input = ResponseSuggestionInput(
            response_type=plan.response_type if plan else "",
            current_subject=draft.subject,
            current_body_text=draft.body_text or "",
            reviewed_classification_summary=classification.summary if classification else None,
            verified_requested_items=[
                {
                    "source_id": str(item.id),
                    "item_text": item.item_text,
                    "status": item.status,
                }
                for item in items
            ],
            approved_document_metadata=[
                {
                    "source_id": str(document.id),
                    "title": document.canonical_title,
                    "document_type": document.document_type,
                    "approval_status": document.approval_status,
                }
                for document in documents
            ],
            tone_guidelines="Concise, factual, professional, and non-committal.",
        )
        initial_graph_identity = (
            draft.graph_draft_message_id,
            draft.graph_change_key,
            draft.graph_etag,
        )
        # No database transaction is held across external provider I/O.
        await self.session.rollback()
        suggestion = await self.provider.suggest(provider_input, uuid.uuid4())
        self._verify_claims(suggestion, source_values)
        locked = await self.session.scalar(
            select(OutboundDraft).where(OutboundDraft.id == draft_id).with_for_update()
        )
        if locked is None or locked.local_revision != expected_revision:
            raise StateConflictError("Draft revision changed while the suggestion was generated.")
        if locked.draft_status in {
            CommunicationDraftStatus.PENDING_SEND_APPROVAL,
            CommunicationDraftStatus.APPROVED_TO_SEND,
            CommunicationDraftStatus.SEND_QUEUED,
            CommunicationDraftStatus.SENDING,
            CommunicationDraftStatus.SEND_ACCEPTED,
            CommunicationDraftStatus.SEND_AMBIGUOUS,
            CommunicationDraftStatus.SENT_COPY_VERIFIED,
        }:
            raise StateConflictError(
                "Draft entered approval or send processing while the suggestion was generated."
            )
        if (
            locked.graph_draft_message_id,
            locked.graph_change_key,
            locked.graph_etag,
        ) != initial_graph_identity:
            raise StateConflictError(
                "Graph draft identity changed while the suggestion was generated."
            )
        findings = validate_draft_content(
            subject=suggestion.subject,
            body_text=suggestion.body_text,
            body_html=suggestion.body_html,
            attachment_count=len(selected),
        )
        if len(suggestion.body_text) + len(suggestion.body_html or "") > (
            self.settings.communication_max_body_chars
        ):
            findings.append("BODY_TOO_LARGE")
        if findings:
            raise StateConflictError(
                "AI suggestion failed controlled draft validation.",
                details={"blockers": findings},
            )
        locked.subject = suggestion.subject
        locked.body_text = suggestion.body_text
        locked.body_html = suggestion.body_html
        await invalidate_approval(self.session, locked, "AI wording suggestion applied")
        await create_version(
            self.session,
            locked,
            actor_id=actor.actor_id,
            change_reason="AI_SUGGESTION_REQUIRES_HUMAN_REVIEW",
        )
        locked.draft_status = CommunicationDraftStatus.REVIEW_IN_PROGRESS
        self.session.add(
            TaskEvent(
                task_id=locked.task_id,
                event_type="AI_RESPONSE_SUGGESTION_APPLIED",
                actor_id=actor.actor_id,
                event_metadata={
                    "draft_id": str(locked.id),
                    "revision": locked.local_revision,
                    "warning_count": len(suggestion.warnings),
                },
                occurred_at=utcnow(),
            )
        )
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="outbound_draft",
            entity_id=locked.id,
            action="ai_wording_suggestion_applied_for_review",
            after={"revision": locked.local_revision, "status": locked.draft_status},
            metadata={"claim_count": len(suggestion.claims_used)},
        )
        await self.session.commit()
        return locked

    @staticmethod
    def _verify_claims(suggestion: ResponseSuggestion, source_values: dict[str, str]) -> None:
        for claim in suggestion.claims_used:
            supported_fields = {
                "verified_requested_items",
                "approved_document_metadata",
                "reviewed_classification_summary",
            }
            if not any(
                claim.field == field
                or claim.field.startswith(f"{field}[")
                or claim.field.startswith(f"{field}.")
                for field in supported_fields
            ):
                raise StateConflictError("AI suggestion cites an unsupported application field.")
            source = source_values.get(claim.source_id)
            if source is None or claim.text.strip().lower() not in source.lower():
                raise StateConflictError(
                    "AI suggestion contains a factual claim that is not supported "
                    "by approved application data."
                )

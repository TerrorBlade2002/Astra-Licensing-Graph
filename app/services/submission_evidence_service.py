"""Human-only final actions, submission evidence, and evidence-gated case updates."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import (
    PORTAL_SUBMISSION_AMBIGUOUS_TOTAL,
    PORTAL_SUBMISSIONS_RECORDED_TOTAL,
)
from app.deadlines.enums import DeadlineSeverity, DeadlineStatus, DeadlineType
from app.documents.enums import ApprovalStatus, LifecycleStatus
from app.forms.enums import FormInstanceStatus
from app.licensing.audit import add_licensing_audit
from app.licensing.enums import CaseStage
from app.models import (
    BrowserSession,
    ComplianceCase,
    ComplianceDeadline,
    Document,
    DocumentLink,
    FormInstance,
    HumanHandoff,
    PortalAttestationRecord,
    PortalDefinition,
    PortalPaymentRecord,
    PortalRun,
    PreSubmissionSnapshot,
    SubmissionEvidence,
    UserPrincipal,
)
from app.models.mixins import utcnow
from app.portals.enums import (
    ACTIVE_BROWSER_SESSION_STATUSES,
    AttestationStatus,
    HandoffStatus,
    HandoffType,
    PaymentStatus,
    PortalJobType,
    PortalRunStatus,
    SnapshotStatus,
    SubmissionEvidenceType,
)
from app.repositories.portal_jobs import PortalJobRepository
from app.services.compliance_case_service import ComplianceCaseService
from app.services.portal_run_service import PortalRunService
from app.services.portal_session_service import PortalSessionService


class SubmissionEvidenceService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def ensure_attestation(
        self,
        run_id: uuid.UUID,
        *,
        attestation_type: str,
        required_actor_id: uuid.UUID,
        text_fingerprint: str | None,
        displayed_text_reference: str | None,
    ) -> PortalAttestationRecord:
        run = await self._run(run_id)
        if required_actor_id != run.assigned_signatory_id:
            raise StateConflictError("Attestation must be assigned to the approved signatory.")
        existing = await self.session.scalar(
            select(PortalAttestationRecord).where(
                PortalAttestationRecord.portal_run_id == run.id,
                PortalAttestationRecord.attestation_type == attestation_type,
            )
        )
        if existing:
            if (
                existing.attestation_text_fingerprint
                and text_fingerprint
                and existing.attestation_text_fingerprint != text_fingerprint
            ):
                existing.status = AttestationStatus.FAILED.value
                run.status = PortalRunStatus.FAILED_REVIEW.value
                run.current_stage = run.status
                raise StateConflictError("Portal attestation text changed; review is required.")
            return existing
        record = PortalAttestationRecord(
            portal_run_id=run.id,
            attestation_type=attestation_type,
            required_actor_id=required_actor_id,
            status=AttestationStatus.WAITING.value,
            attestation_text_fingerprint=text_fingerprint,
            displayed_text_reference=displayed_text_reference,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def record_attestation_completion(
        self,
        attestation_id: uuid.UUID,
        *,
        actor: CurrentActor,
        resulting_page_category: str,
        evidence_reference: str | None,
    ) -> PortalAttestationRecord:
        record = await self.session.get(PortalAttestationRecord, attestation_id)
        if record is None:
            raise NotFoundError("Portal attestation record not found.")
        if record.status != AttestationStatus.WAITING.value:
            raise StateConflictError("Attestation is not awaiting human completion.")
        if record.required_actor_id is None:
            raise StateConflictError("Attestation has no assigned authorized person.")
        await self._assert_actor_user(actor, record.required_actor_id)
        if resulting_page_category in {"attestation", "final_submit"}:
            raise StateConflictError("Portal state does not demonstrate completed attestation.")
        if not evidence_reference:
            raise StateConflictError(
                "Attestation requires portal evidence or an approved evidence reference."
            )
        record.status = AttestationStatus.COMPLETED_BY_HUMAN.value
        record.completed_by_actor = actor.actor_id
        record.completed_at = utcnow()
        record.evidence_reference = evidence_reference[:1000]
        handoff = await self.session.scalar(
            select(HumanHandoff)
            .where(
                HumanHandoff.portal_run_id == record.portal_run_id,
                HumanHandoff.handoff_type == HandoffType.ATTESTATION.value,
                HumanHandoff.status.in_(
                    (HandoffStatus.REQUESTED.value, HandoffStatus.ACTIVE.value)
                ),
            )
            .order_by(HumanHandoff.requested_at.desc())
        )
        if handoff:
            handoff.status = HandoffStatus.COMPLETED.value
            handoff.completed_at = utcnow()
            handoff.result = "COMPLETED_BY_HUMAN"
            handoff.evidence_reference = evidence_reference[:1000]
            if handoff.browser_session_id is None:
                run = await self._run(record.portal_run_id)
                run.status = PortalRunStatus.WAITING_OPERATOR.value
                run.current_stage = run.status
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_attestation_record",
            entity_id=record.id,
            action="portal_attestation_human_completion_recorded",
            after={"status": record.status, "resulting_page_category": resulting_page_category},
        )
        await self.session.commit()
        return record

    async def record_signature_completion(
        self,
        handoff_id: uuid.UUID,
        *,
        actor: CurrentActor,
        evidence_reference: str | None,
    ) -> HumanHandoff:
        handoff = await self.session.get(HumanHandoff, handoff_id)
        if (
            handoff is None
            or handoff.handoff_type != HandoffType.SIGNATURE.value
            or handoff.status != HandoffStatus.ACTIVE.value
        ):
            raise StateConflictError("Signature handoff is not under active human control.")
        if handoff.requested_from_user_id is None:
            raise StateConflictError("Signature handoff has no assigned signatory.")
        await self._assert_actor_user(actor, handoff.requested_from_user_id)
        run = await self._run(handoff.portal_run_id)
        if run.form_instance_id is None:
            raise StateConflictError("Signature handoff has no governed form instance.")
        form = await self.session.get(FormInstance, run.form_instance_id)
        if (
            form is None
            or not form.signature_required
            or form.status
            not in {
                FormInstanceStatus.SIGNED.value,
                FormInstanceStatus.READY_FOR_SUBMISSION.value,
            }
            or form.signed_document_id is None
        ):
            raise StateConflictError("Approved signed-form evidence is required.")
        await self._validate_evidence_document(form.signed_document_id, run)
        handoff.status = HandoffStatus.COMPLETED.value
        handoff.completed_at = utcnow()
        handoff.result = "SIGNED_BY_AUTHORIZED_PERSON"
        handoff.evidence_reference = (
            evidence_reference[:1000]
            if evidence_reference
            else f"document:{form.signed_document_id}"
        )
        if handoff.browser_session_id is None:
            run.status = PortalRunStatus.WAITING_OPERATOR.value
            run.current_stage = run.status
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="human_handoff",
            entity_id=handoff.id,
            action="portal_signature_human_completion_recorded",
            after={"signed_document_id": str(form.signed_document_id)},
        )
        await self.session.commit()
        return handoff

    async def ensure_payment(
        self,
        run_id: uuid.UUID,
        *,
        expected_fee_amount: object | None,
        currency: str | None,
        fee_summary: dict[str, Any] | None,
    ) -> PortalPaymentRecord:
        run = await self._run(run_id)
        payment = await self.session.scalar(
            select(PortalPaymentRecord).where(PortalPaymentRecord.portal_run_id == run.id)
        )
        if payment is None:
            payment = PortalPaymentRecord(
                portal_run_id=run.id,
                status=PaymentStatus.REVIEW_REQUIRED.value,
                expected_fee_amount=expected_fee_amount,
                currency=currency,
                portal_fee_summary=fee_summary,
            )
            self.session.add(payment)
        elif payment.status == PaymentStatus.APPROVED.value and (
            payment.expected_fee_amount != expected_fee_amount
            or payment.currency != currency
            or payment.portal_fee_summary != fee_summary
        ):
            payment.status = PaymentStatus.REVIEW_REQUIRED.value
            run.status = PortalRunStatus.DISCREPANCIES_FOUND.value
            run.current_stage = run.status
        await self.session.flush()
        return payment

    async def approve_payment(
        self, payment_id: uuid.UUID, *, actor: CurrentActor
    ) -> PortalPaymentRecord:
        payment = await self._payment(payment_id)
        run = await self._run(payment.portal_run_id)
        if run.assigned_payment_approver_id is None:
            raise StateConflictError("Run has no assigned payment approver.")
        await self._assert_actor_user(actor, run.assigned_payment_approver_id)
        if payment.status != PaymentStatus.REVIEW_REQUIRED.value:
            raise StateConflictError("Payment is not awaiting approval.")
        payment.status = PaymentStatus.APPROVED.value
        payment.approved_by_actor = actor.actor_id
        payment.approved_at = utcnow()
        await self.session.commit()
        return payment

    async def record_external_payment(
        self,
        payment_id: uuid.UUID,
        *,
        actor: CurrentActor,
        payment_reference_redacted: str | None,
        receipt_document_id: uuid.UUID | None,
    ) -> PortalPaymentRecord:
        payment = await self._payment(payment_id)
        run = await self._run(payment.portal_run_id)
        if run.assigned_payment_approver_id is None:
            raise StateConflictError("Run has no assigned payment approver.")
        await self._assert_actor_user(actor, run.assigned_payment_approver_id)
        if payment.status != PaymentStatus.APPROVED.value:
            raise StateConflictError("Payment must be approved before a human records payment.")
        if receipt_document_id:
            await self._validate_evidence_document(receipt_document_id, run)
        payment.status = PaymentStatus.PAID_EXTERNALLY.value
        payment.paid_by_actor = actor.actor_id
        payment.paid_at = utcnow()
        payment.payment_reference_redacted = payment_reference_redacted
        payment.receipt_document_id = receipt_document_id
        handoff = await self.session.scalar(
            select(HumanHandoff)
            .where(
                HumanHandoff.portal_run_id == run.id,
                HumanHandoff.handoff_type == HandoffType.PAYMENT.value,
                HumanHandoff.status.in_(
                    (HandoffStatus.REQUESTED.value, HandoffStatus.ACTIVE.value)
                ),
            )
            .order_by(HumanHandoff.requested_at.desc())
        )
        if handoff:
            handoff.status = HandoffStatus.COMPLETED.value
            handoff.completed_at = utcnow()
            handoff.result = "PAID_EXTERNALLY"
            if handoff.browser_session_id is None:
                run.status = PortalRunStatus.WAITING_OPERATOR.value
                run.current_stage = run.status
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_payment_record",
            entity_id=payment.id,
            action="external_payment_recorded",
            after={"status": payment.status, "has_receipt": bool(receipt_document_id)},
        )
        await self.session.commit()
        return payment

    async def request_final_submit_handoff(
        self, run_id: uuid.UUID, *, actor: CurrentActor
    ) -> HumanHandoff:
        run = await self._run(run_id)
        await PortalRunService(self.session, self.settings).revalidate_governance(run)
        snapshot = await self.session.scalar(
            select(PreSubmissionSnapshot).where(
                PreSubmissionSnapshot.portal_run_id == run.id,
                PreSubmissionSnapshot.status == SnapshotStatus.APPROVED.value,
            )
        )
        if snapshot is None:
            raise StateConflictError("An exact approved pre-submission snapshot is required.")
        attestations = list(
            await self.session.scalars(
                select(PortalAttestationRecord).where(
                    PortalAttestationRecord.portal_run_id == run.id
                )
            )
        )
        if any(
            item.status
            not in {
                AttestationStatus.NOT_REQUIRED.value,
                AttestationStatus.COMPLETED_BY_HUMAN.value,
            }
            for item in attestations
        ):
            raise StateConflictError("Required human attestation is incomplete.")
        if run.form_instance_id:
            form = await self.session.get(FormInstance, run.form_instance_id)
            if (
                form
                and form.signature_required
                and form.status
                not in {
                    FormInstanceStatus.SIGNED.value,
                    FormInstanceStatus.READY_FOR_SUBMISSION.value,
                }
            ):
                raise StateConflictError("Required signed form evidence is incomplete.")
        payment = await self.session.scalar(
            select(PortalPaymentRecord).where(PortalPaymentRecord.portal_run_id == run.id)
        )
        if payment and payment.status not in {
            PaymentStatus.NOT_REQUIRED.value,
            PaymentStatus.PAID_EXTERNALLY.value,
        }:
            raise StateConflictError("Required human payment is incomplete.")
        if run.assigned_operator_id is None:
            raise StateConflictError("Run has no assigned final-submit operator.")
        browser_session = await self.session.scalar(
            select(BrowserSession)
            .where(
                BrowserSession.portal_run_id == run.id,
                BrowserSession.operator_user_id == run.assigned_operator_id,
                BrowserSession.session_status.in_(ACTIVE_BROWSER_SESSION_STATUSES),
            )
            .order_by(BrowserSession.started_at.desc())
        )
        if browser_session is None:
            raise StateConflictError(
                "A current operator-owned browser session is required for final-page verification."
            )
        return await PortalSessionService(self.session, self.settings).create_handoff(
            run.id,
            actor=actor,
            handoff_type=HandoffType.FINAL_SUBMIT.value,
            requested_from_user_id=run.assigned_operator_id,
            browser_session_id=browser_session.id,
        )

    async def request_submission_reconciliation(
        self,
        run_id: uuid.UUID,
        *,
        actor: CurrentActor,
        reported_outcome: str,
        reported_page_category: str,
        reported_ambiguous: bool,
    ) -> PortalRun:
        """Queue read-only verification after the assigned human's final action."""
        run = await self._run(run_id)
        handoff = await self.session.scalar(
            select(HumanHandoff)
            .where(
                HumanHandoff.portal_run_id == run.id,
                HumanHandoff.handoff_type == HandoffType.FINAL_SUBMIT.value,
            )
            .order_by(HumanHandoff.requested_at.desc())
        )
        if handoff is None or handoff.status != HandoffStatus.ACTIVE.value:
            raise StateConflictError("No active human final-submit handoff exists.")
        if handoff.requested_from_user_id is None or handoff.browser_session_id is None:
            raise StateConflictError("Final-submit handoff lacks an owned browser session.")
        await self._assert_actor_user(actor, handoff.requested_from_user_id)
        if run.status == PortalRunStatus.SUBMITTED.value:
            raise StateConflictError("Submission is already recorded; do not submit again.")
        handoff.result = "HUMAN_ACTION_REPORTED"
        handoff.operator_confirmation = (
            f"outcome={reported_outcome[:40]}; "
            f"page={reported_page_category[:80]}; ambiguous={reported_ambiguous}"
        )
        run.status = PortalRunStatus.SUBMISSION_RESULT_PENDING.value
        run.current_stage = run.status
        await PortalJobRepository(self.session).enqueue(
            job_type=PortalJobType.CAPTURE_SUBMISSION_RESULT,
            idempotency_key=f"portal-submission-capture:{handoff.id}",
            portal_run_id=run.id,
            browser_session_id=handoff.browser_session_id,
            payload={
                "handoff_id": str(handoff.id),
                "reported_by_actor": actor.actor_id,
                "reported_outcome": reported_outcome[:40],
                "reported_ambiguous": reported_ambiguous,
            },
            max_attempts=1,
        )
        await self.session.commit()
        return run

    async def capture_submission_result(
        self,
        run_id: uuid.UUID,
        *,
        actor: CurrentActor,
        outcome: str,
        resulting_page_category: str,
        ambiguous: bool,
        confirmation_number: str | None,
        filing_reference: str | None,
        evidence_document_id: uuid.UUID | None,
    ) -> PortalRun:
        run = await self._run(run_id)
        handoff = await self.session.scalar(
            select(HumanHandoff)
            .where(
                HumanHandoff.portal_run_id == run.id,
                HumanHandoff.handoff_type == HandoffType.FINAL_SUBMIT.value,
            )
            .order_by(HumanHandoff.requested_at.desc())
        )
        if handoff is None or handoff.status not in {
            HandoffStatus.ACTIVE.value,
            HandoffStatus.COMPLETED.value,
        }:
            raise StateConflictError("No active human final-submit handoff exists.")
        if handoff.requested_from_user_id:
            await self._assert_actor_user(actor, handoff.requested_from_user_id)
        if run.status == PortalRunStatus.SUBMITTED.value:
            raise StateConflictError("Submission result is already recorded; do not submit again.")
        if ambiguous or outcome.upper() not in {"CONFIRMED", "FAILED"}:
            run.status = PortalRunStatus.SUBMISSION_RESULT_PENDING.value
            run.current_stage = run.status
            run.last_error_code = "ambiguous_submission_result"
            run.last_error_message = (
                "Final action outcome is ambiguous. Reconcile evidence; never retry submission."
            )
            await self.session.commit()
            PORTAL_SUBMISSION_AMBIGUOUS_TOTAL.inc()
            return run
        if outcome.upper() == "FAILED":
            run.status = PortalRunStatus.SUBMISSION_FAILED.value
            run.current_stage = run.status
            handoff.status = HandoffStatus.COMPLETED.value
            handoff.completed_at = utcnow()
            await self.session.commit()
            return run
        if resulting_page_category != "confirmation":
            raise StateConflictError("Confirmed submission requires a reviewed confirmation page.")
        if not (confirmation_number or filing_reference or evidence_document_id):
            raise StateConflictError("Verified confirmation evidence is required.")
        if evidence_document_id:
            await self._validate_evidence_document(evidence_document_id, run)
        evidence = SubmissionEvidence(
            portal_run_id=run.id,
            evidence_type=SubmissionEvidenceType.PORTAL_CONFIRMATION.value,
            confirmation_number=confirmation_number,
            filing_reference=filing_reference,
            submission_status="SUBMITTED",
            submitted_by_actor=actor.actor_id,
            submitted_at=utcnow(),
            source_document_id=evidence_document_id,
            evidence_verified_by_actor=actor.actor_id,
            verified_at=utcnow(),
        )
        self.session.add(evidence)
        await self.session.flush()
        handoff.status = HandoffStatus.COMPLETED.value
        handoff.completed_at = utcnow()
        handoff.result = "CONFIRMED"
        run.status = PortalRunStatus.SUBMITTED.value
        run.current_stage = run.status
        run.submitted_at = evidence.submitted_at
        run.last_error_code = None
        run.last_error_message = None
        await self._advance_case(run, evidence, actor)
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_run",
            entity_id=run.id,
            action="human_submission_evidence_verified",
            after={
                "status": run.status,
                "submission_evidence_id": str(evidence.id),
                "case_updated": True,
            },
        )
        await self.session.commit()
        PORTAL_SUBMISSIONS_RECORDED_TOTAL.inc()
        return run

    async def add_evidence(
        self,
        run_id: uuid.UUID,
        *,
        actor: CurrentActor,
        fields: dict[str, Any],
    ) -> SubmissionEvidence:
        run = await self._run(run_id)
        if fields["evidence_type"] not in {item.value for item in SubmissionEvidenceType}:
            raise StateConflictError("Unknown submission evidence type.")
        if fields.get("source_document_id"):
            await self._validate_evidence_document(fields["source_document_id"], run)
        for uri_field in ("screenshot_storage_uri", "receipt_storage_uri"):
            uri = fields.get(uri_field)
            if uri and not uri.startswith("sharepoint://"):
                raise StateConflictError(
                    "Submission artifacts must use governed SharePoint storage."
                )
        if not (
            fields.get("confirmation_number")
            or fields.get("filing_reference")
            or fields.get("source_document_id")
            or fields.get("evidence_sha256")
        ):
            raise StateConflictError("Submission evidence requires a verifiable reference or hash.")
        evidence = SubmissionEvidence(
            portal_run_id=run.id,
            submitted_by_actor=actor.actor_id,
            evidence_verified_by_actor=actor.actor_id,
            verified_at=utcnow(),
            **fields,
        )
        self.session.add(evidence)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="submission_evidence",
            entity_id=evidence.id,
            action="submission_evidence_recorded",
            after={"evidence_type": evidence.evidence_type},
        )
        await self.session.commit()
        return evidence

    async def _advance_case(
        self, run: PortalRun, evidence: SubmissionEvidence, actor: CurrentActor
    ) -> None:
        case = await self.session.get(ComplianceCase, run.compliance_case_id)
        if case is None:
            raise NotFoundError("Compliance case not found.")
        if case.current_stage != CaseStage.SUBMISSION_PENDING.value:
            raise StateConflictError(
                "Case is not at SUBMISSION_PENDING; submission evidence cannot bypass stages."
            )
        portal = await self.session.get(PortalDefinition, run.portal_definition_id)
        to_stage = (
            CaseStage.SUBMITTED_TO_VENDOR.value
            if portal and portal.portal_type in {"LICENSING_VENDOR", "BOND_PROVIDER"}
            else CaseStage.SUBMITTED_TO_REGULATOR.value
        )
        await ComplianceCaseService(self.session, self.settings).transition(
            case.id,
            to_stage=to_stage,
            actor=actor,
            reason="Human portal submission verified.",
            evidence={
                "submission_reference": str(evidence.id),
                "portal_run_id": str(run.id),
            },
            commit=False,
        )
        follow_up_due = utcnow() + timedelta(days=7)
        materialization_key = f"portal-follow-up:{run.id}"
        existing = await self.session.scalar(
            select(ComplianceDeadline.id).where(
                ComplianceDeadline.materialization_key == materialization_key
            )
        )
        if not existing:
            self.session.add(
                ComplianceDeadline(
                    obligation_id=case.obligation_id,
                    compliance_case_id=case.id,
                    deadline_type=DeadlineType.FOLLOW_UP.value,
                    due_at=follow_up_due,
                    internal_target_at=follow_up_due,
                    status=DeadlineStatus.SCHEDULED.value,
                    severity=DeadlineSeverity.IMPORTANT.value,
                    assigned_owner=case.assigned_owner,
                    materialization_key=materialization_key,
                    applied_adjustment="NONE",
                )
            )

    async def _validate_evidence_document(self, document_id: uuid.UUID, run: PortalRun) -> Document:
        document = await self.session.get(Document, document_id)
        if document is None:
            raise NotFoundError("Evidence document not found.")
        if (
            document.approval_status != ApprovalStatus.APPROVED.value
            or document.lifecycle_status != LifecycleStatus.ACTIVE.value
            or document.current_version_id is None
        ):
            raise StateConflictError("Evidence document is not approved, active, and available.")
        linked = await self.session.scalar(
            select(DocumentLink.id).where(
                DocumentLink.document_id == document.id,
                DocumentLink.linked_entity_id == run.legal_entity_id,
            )
        )
        if not linked:
            raise StateConflictError("Evidence document is not linked to the run's legal entity.")
        return document

    async def _assert_actor_user(
        self, actor: CurrentActor, expected_user_id: uuid.UUID
    ) -> UserPrincipal:
        principal = await self.session.scalar(
            select(UserPrincipal).where(
                UserPrincipal.tenant_id == actor.tenant_id,
                UserPrincipal.object_id == actor.object_id,
            )
        )
        if principal is None or principal.id != expected_user_id:
            raise StateConflictError("Authenticated user is not assigned to this human action.")
        return principal

    async def _payment(self, payment_id: uuid.UUID) -> PortalPaymentRecord:
        payment = await self.session.get(PortalPaymentRecord, payment_id)
        if payment is None:
            raise NotFoundError("Portal payment record not found.")
        return payment

    async def _run(self, run_id: uuid.UUID) -> PortalRun:
        run = await self.session.get(PortalRun, run_id)
        if run is None:
            raise NotFoundError("Portal run not found.")
        return run

"""Obligations, compliance cases, stage transitions, and information requests."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.config import Settings
from app.core.exceptions import InvalidStateTransitionError, NotFoundError, StateConflictError
from app.core.metrics import (
    COMPLIANCE_CASE_STAGE_DURATION_SECONDS,
    COMPLIANCE_CASES_BLOCKED,
    COMPLIANCE_CASES_OPEN,
    COMPLIANCE_CASES_OVERDUE,
    INFORMATION_REQUESTS_OPEN,
)
from app.deadlines.alerts import information_request_alert
from app.licensing.audit import add_licensing_audit, record_notification
from app.licensing.enums import (
    CaseInformationRequestStatus,
    CasePriority,
    CaseStage,
    CaseStatus,
    CaseType,
    ObligationStatus,
    ObligationType,
)
from app.licensing.stages import initial_stage, next_stages, validate_transition
from app.models import (
    CaseInformationRequest,
    ComplianceCase,
    ComplianceCaseStageEvent,
    ComplianceObligation,
    DocumentPacket,
    FormInstance,
    Jurisdiction,
    LegalEntity,
    LicenseBond,
    LicenseInventory,
    Organization,
)
from app.models.mixins import utcnow
from app.services.license_inventory_service import slugify

#: Obligation type -> the case type opened to satisfy it.
_CASE_TYPE_FOR_OBLIGATION: dict[str, str] = {
    ObligationType.LICENSE_RENEWAL.value: CaseType.LICENSE_RENEWAL.value,
    ObligationType.BOND_RENEWAL.value: CaseType.BOND_RENEWAL.value,
    ObligationType.ANNUAL_REPORT.value: CaseType.ANNUAL_REPORT.value,
    ObligationType.FINANCIAL_DOCUMENT.value: CaseType.FINANCIAL_DOCUMENT.value,
    ObligationType.CERTIFICATE_RENEWAL.value: CaseType.OTHER.value,
    ObligationType.INITIAL_APPLICATION.value: CaseType.INITIAL_LICENSE.value,
    ObligationType.AMENDMENT.value: CaseType.LICENSE_AMENDMENT.value,
    ObligationType.DEFICIENCY_RESPONSE.value: CaseType.DEFICIENCY_RESPONSE.value,
    ObligationType.INFORMATION_RESPONSE.value: CaseType.INFORMATION_RESPONSE.value,
    ObligationType.SURRENDER.value: CaseType.SURRENDER.value,
    ObligationType.OTHER.value: CaseType.OTHER.value,
}


class ComplianceCaseService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    # ---------------------------------------------------------------- obligations
    async def _validate_obligation_links(self, fields: dict[str, Any]) -> None:
        """Reject cross-entity and dangling obligation references before persistence."""
        entity_id = fields["legal_entity_id"]
        entity = await self.session.get(LegalEntity, entity_id)
        if entity is None:
            raise NotFoundError("Legal entity not found.")

        license_id = fields.get("license_id")
        license_record = (
            await self.session.get(LicenseInventory, license_id) if license_id else None
        )
        if license_id and license_record is None:
            raise NotFoundError("License not found.")
        if license_record and license_record.legal_entity_id != entity_id:
            raise StateConflictError("License and obligation must belong to the same legal entity.")

        bond_id = fields.get("bond_id")
        bond = await self.session.get(LicenseBond, bond_id) if bond_id else None
        if bond_id and bond is None:
            raise NotFoundError("Bond not found.")
        if bond and bond.legal_entity_id != entity_id:
            raise StateConflictError("Bond and obligation must belong to the same legal entity.")
        if bond and license_id and bond.license_id and bond.license_id != license_id:
            raise StateConflictError("Bond is not associated with the selected license.")

        jurisdiction_id = fields.get("jurisdiction_id")
        if jurisdiction_id and await self.session.get(Jurisdiction, jurisdiction_id) is None:
            raise NotFoundError("Jurisdiction not found.")
        if license_record and jurisdiction_id and license_record.jurisdiction_id != jurisdiction_id:
            raise StateConflictError("License and obligation must reference the same jurisdiction.")
        if bond and jurisdiction_id and bond.jurisdiction_id not in (None, jurisdiction_id):
            raise StateConflictError("Bond and obligation must reference the same jurisdiction.")

        for field in ("vendor_organization_id", "regulator_organization_id"):
            organization_id = fields.get(field)
            if organization_id and await self.session.get(Organization, organization_id) is None:
                raise NotFoundError(
                    f"{field.removesuffix('_id').replace('_', ' ').title()} not found."
                )

    async def create_obligation(
        self, *, actor: CurrentActor | None, commit: bool = True, **fields: Any
    ) -> ComplianceObligation:
        await self._validate_obligation_links(fields)
        entity = await self.session.get(LegalEntity, fields["legal_entity_id"])
        assert entity is not None
        obligation_type = fields["obligation_type"]
        if obligation_type not in {member.value for member in ObligationType}:
            raise StateConflictError(f"Unknown obligation type {obligation_type!r}.")
        status = fields.get("status") or ObligationStatus.PLANNED.value
        if status not in {member.value for member in ObligationStatus}:
            raise StateConflictError(f"Unknown obligation status {status!r}.")
        obligation_key = (
            fields.get("obligation_key")
            or "-".join(
                [
                    entity.entity_key,
                    slugify(fields["obligation_type"]),
                    slugify(str(fields.get("next_due_date") or utcnow().date())),
                    uuid.uuid4().hex[:6],
                ]
            )[:120]
        )
        obligation = ComplianceObligation(
            obligation_key=obligation_key,
            legal_entity_id=fields["legal_entity_id"],
            license_id=fields.get("license_id"),
            bond_id=fields.get("bond_id"),
            jurisdiction_id=fields.get("jurisdiction_id"),
            obligation_type=obligation_type,
            title=fields["title"],
            status=status,
            recurrence_rule=fields.get("recurrence_rule"),
            statutory_due_date=fields.get("statutory_due_date"),
            next_due_date=fields.get("next_due_date"),
            internal_start_date=fields.get("internal_start_date"),
            responsible_owner=fields.get("responsible_owner"),
            vendor_organization_id=fields.get("vendor_organization_id"),
            regulator_organization_id=fields.get("regulator_organization_id"),
            requirement_source_ids=fields.get("requirement_source_ids") or [],
            predecessor_obligation_id=fields.get("predecessor_obligation_id"),
            notes=fields.get("notes"),
        )
        self.session.add(obligation)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="compliance_obligation",
            entity_id=obligation.id,
            action="obligation_created",
            after={"type": obligation.obligation_type, "due": str(obligation.next_due_date)},
        )
        if commit:
            await self.session.commit()
        return obligation

    async def update_obligation(
        self,
        obligation_id: uuid.UUID,
        *,
        actor: CurrentActor,
        commit: bool = True,
        **changes: Any,
    ) -> ComplianceObligation:
        obligation = await self.session.get(ComplianceObligation, obligation_id)
        if obligation is None:
            raise NotFoundError("Obligation not found.")
        if "status" in changes and changes["status"] not in {
            member.value for member in ObligationStatus
        }:
            raise StateConflictError(f"Unknown obligation status {changes['status']!r}.")
        before = {field: getattr(obligation, field) for field in changes}
        for field, value in changes.items():
            setattr(obligation, field, value)
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="compliance_obligation",
            entity_id=obligation.id,
            action="obligation_updated",
            before=before,
            after={field: getattr(obligation, field) for field in changes},
        )
        if commit:
            await self.session.commit()
        return obligation

    async def create_next_obligation(
        self,
        obligation_id: uuid.UUID,
        *,
        actor: CurrentActor | None = None,
        next_due_date: date | None = None,
        commit: bool = True,
    ) -> ComplianceObligation | None:
        """Roll a satisfied recurring obligation forward one cycle."""
        previous = await self.session.get(ComplianceObligation, obligation_id)
        if previous is None:
            raise NotFoundError("Obligation not found.")
        if not previous.recurrence_rule:
            return None
        existing = await self.session.scalar(
            select(ComplianceObligation.id).where(
                ComplianceObligation.predecessor_obligation_id == previous.id
            )
        )
        if existing:
            return None

        due = next_due_date
        if due is None and previous.next_due_date:
            # Default to a one-year cycle; the deadline engine refines the date
            # from the licence's new expiration during materialization.
            try:
                due = previous.next_due_date.replace(year=previous.next_due_date.year + 1)
            except ValueError:
                due = previous.next_due_date + timedelta(days=365)

        return await self.create_obligation(
            actor=actor,
            commit=commit,
            legal_entity_id=previous.legal_entity_id,
            license_id=previous.license_id,
            bond_id=previous.bond_id,
            jurisdiction_id=previous.jurisdiction_id,
            obligation_type=previous.obligation_type,
            title=previous.title,
            status=ObligationStatus.PLANNED.value,
            recurrence_rule=previous.recurrence_rule,
            next_due_date=due,
            responsible_owner=previous.responsible_owner,
            vendor_organization_id=previous.vendor_organization_id,
            regulator_organization_id=previous.regulator_organization_id,
            requirement_source_ids=list(previous.requirement_source_ids or []),
            predecessor_obligation_id=previous.id,
        )

    # --------------------------------------------------------------------- cases
    async def open_case(
        self,
        obligation_id: uuid.UUID,
        *,
        actor: CurrentActor | None,
        assigned_owner: str | None = None,
        priority: str | None = None,
        commit: bool = True,
    ) -> ComplianceCase:
        """Open a case for an obligation, or return the existing open one."""
        obligation = await self.session.get(ComplianceObligation, obligation_id)
        if obligation is None:
            raise NotFoundError("Obligation not found.")
        existing = await self.session.scalar(
            select(ComplianceCase).where(
                ComplianceCase.obligation_id == obligation_id,
                ComplianceCase.status.not_in(
                    (CaseStatus.COMPLETED.value, CaseStatus.CANCELLED.value)
                ),
            )
        )
        if existing is not None:
            return existing

        entity = await self.session.get(LegalEntity, obligation.legal_entity_id)
        case_key = "-".join(
            [
                (entity.entity_key if entity else "entity"),
                slugify(obligation.obligation_type),
                utcnow().strftime("%Y%m%d"),
                uuid.uuid4().hex[:6],
            ]
        )[:120]
        case = ComplianceCase(
            case_key=case_key,
            obligation_id=obligation.id,
            legal_entity_id=obligation.legal_entity_id,
            license_id=obligation.license_id,
            bond_id=obligation.bond_id,
            case_type=_CASE_TYPE_FOR_OBLIGATION.get(
                obligation.obligation_type, CaseType.OTHER.value
            ),
            current_stage=initial_stage(),
            status=CaseStatus.OPEN.value,
            priority=priority or CasePriority.NORMAL.value,
            statutory_due_date=obligation.statutory_due_date or obligation.next_due_date,
            internal_target_date=obligation.internal_start_date,
            assigned_owner=assigned_owner or obligation.responsible_owner,
            vendor_organization_id=obligation.vendor_organization_id,
            regulator_organization_id=obligation.regulator_organization_id,
            created_by_actor=actor.actor_id if actor else "licensing-worker",
            stage_entered_at=utcnow(),
        )
        self.session.add(case)
        await self.session.flush()
        self.session.add(
            ComplianceCaseStageEvent(
                compliance_case_id=case.id,
                from_stage=None,
                to_stage=case.current_stage,
                actor_id=actor.actor_id if actor else "licensing-worker",
                reason="Case opened.",
                evidence={"obligation_id": str(obligation.id)},
                occurred_at=utcnow(),
            )
        )
        obligation.status = ObligationStatus.IN_CASE.value
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="compliance_case",
            entity_id=case.id,
            action="case_opened",
            after={"case_type": case.case_type, "stage": case.current_stage},
        )
        if commit:
            await self.session.commit()
        return case

    async def update_case(
        self,
        case_id: uuid.UUID,
        *,
        actor: CurrentActor,
        commit: bool = True,
        **changes: Any,
    ) -> ComplianceCase:
        """Update case ownership/coordination fields without bypassing stage controls."""
        case = await self.session.get(ComplianceCase, case_id)
        if case is None:
            raise NotFoundError("Compliance case not found.")
        priority = changes.get("priority")
        if priority is not None and priority not in {member.value for member in CasePriority}:
            raise StateConflictError(f"Unknown case priority {priority!r}.")
        for field in ("vendor_organization_id", "regulator_organization_id"):
            organization_id = changes.get(field)
            if organization_id and await self.session.get(Organization, organization_id) is None:
                raise NotFoundError(
                    f"{field.removesuffix('_id').replace('_', ' ').title()} not found."
                )
        before = {field: getattr(case, field) for field in changes}
        for field, value in changes.items():
            setattr(case, field, value)
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="compliance_case",
            entity_id=case.id,
            action="case_updated",
            before=before,
            after={field: getattr(case, field) for field in changes},
        )
        if commit:
            await self.session.commit()
        return case

    async def transition(
        self,
        case_id: uuid.UUID,
        *,
        to_stage: str,
        actor: CurrentActor,
        reason: str | None = None,
        evidence: dict[str, Any] | None = None,
        close_reason: str | None = None,
        commit: bool = True,
    ) -> ComplianceCase:
        """Move a case to a new stage, enforcing every control point."""
        case = await self.session.get(ComplianceCase, case_id)
        if case is None:
            raise NotFoundError("Compliance case not found.")

        payload = dict(evidence or {})

        # A form requiring a signature blocks submission until signed evidence
        # exists. Determined from live data, never from the caller's assertion.
        instances = list(
            await self.session.scalars(
                select(FormInstance).where(FormInstance.compliance_case_id == case.id)
            )
        )
        signature_required = any(i.signature_required for i in instances)
        signature_recorded = any(
            i.signature_required and i.signed_document_id is not None for i in instances
        )

        has_renewed_evidence = bool(
            payload.get("renewed_evidence_document_id")
        ) or await self.session.scalar(
            select(func.count())
            .select_from(ComplianceCaseStageEvent)
            .where(
                ComplianceCaseStageEvent.compliance_case_id == case.id,
                ComplianceCaseStageEvent.to_stage == CaseStage.RENEWED_EVIDENCE_RECEIVED.value,
            )
        )

        # Packet stages carry the packet id automatically when one is approved.
        if to_stage in (
            CaseStage.PACKET_APPROVED.value,
            CaseStage.PACKET_SENT.value,
        ) and not payload.get("document_packet_id"):
            approved = await self.session.scalar(
                select(DocumentPacket.id)
                .where(
                    DocumentPacket.compliance_case_id == case.id,
                    DocumentPacket.status == "APPROVED",
                )
                .order_by(DocumentPacket.version.desc())
            )
            if approved:
                payload["document_packet_id"] = str(approved)
        if to_stage == CaseStage.SIGNED_FORM_RECEIVED.value and not payload.get(
            "signed_document_id"
        ):
            signed = next((i.signed_document_id for i in instances if i.signed_document_id), None)
            if signed:
                payload["signed_document_id"] = str(signed)

        check = validate_transition(
            from_stage=case.current_stage,
            to_stage=to_stage,
            evidence=payload,
            signature_required=signature_required,
            signature_recorded=signature_recorded,
            has_renewed_evidence=bool(has_renewed_evidence),
            close_reason=close_reason or case.close_reason,
        )
        if not check.allowed:
            raise InvalidStateTransitionError(
                check.reason, details={"missing_evidence": list(check.missing_evidence)}
            )

        previous_stage = case.current_stage
        entered = case.stage_entered_at or case.created_at
        seconds = int((utcnow() - entered).total_seconds()) if entered else None

        case.current_stage = to_stage
        case.status = check.resulting_status or case.status
        case.stage_entered_at = utcnow()
        if close_reason:
            case.close_reason = close_reason[:500]
        if to_stage == CaseStage.BLOCKED.value:
            case.blocked_reason = (reason or "Blocked")[:500]
        elif previous_stage == CaseStage.BLOCKED.value:
            case.blocked_reason = None
        if to_stage == CaseStage.COMPLETED.value:
            case.completed_at = utcnow()
            obligation = await self.session.get(ComplianceObligation, case.obligation_id)
            if obligation is not None:
                obligation.status = ObligationStatus.SATISFIED.value

        self.session.add(
            ComplianceCaseStageEvent(
                compliance_case_id=case.id,
                from_stage=previous_stage,
                to_stage=to_stage,
                actor_id=actor.actor_id,
                reason=reason,
                evidence=payload,
                seconds_in_previous_stage=seconds,
                occurred_at=utcnow(),
            )
        )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="compliance_case",
            entity_id=case.id,
            action="case_stage_changed",
            before={"stage": previous_stage},
            after={"stage": to_stage, "status": case.status},
        )
        if seconds is not None:
            COMPLIANCE_CASE_STAGE_DURATION_SECONDS.labels(stage=previous_stage).observe(seconds)
        if commit:
            await self.session.commit()
        return case

    async def timeline(self, case_id: uuid.UUID) -> list[dict[str, Any]]:
        events = list(
            await self.session.scalars(
                select(ComplianceCaseStageEvent)
                .where(ComplianceCaseStageEvent.compliance_case_id == case_id)
                .order_by(ComplianceCaseStageEvent.occurred_at)
            )
        )
        return [
            {
                "id": str(event.id),
                "from_stage": event.from_stage,
                "to_stage": event.to_stage,
                "actor_id": event.actor_id,
                "reason": event.reason,
                "evidence": event.evidence,
                "seconds_in_previous_stage": event.seconds_in_previous_stage,
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in events
        ]

    async def available_transitions(self, case_id: uuid.UUID) -> list[str]:
        case = await self.session.get(ComplianceCase, case_id)
        if case is None:
            raise NotFoundError("Compliance case not found.")
        return list(next_stages(case.current_stage))

    # ------------------------------------------------------- information requests
    async def create_information_request(
        self,
        case_id: uuid.UUID,
        *,
        actor: CurrentActor,
        question_text: str,
        information_definition_id: uuid.UUID | None = None,
        requested_from_actor: str | None = None,
        due_at: Any = None,
        source_email_id: uuid.UUID | None = None,
        source_vendor_question: str | None = None,
        commit: bool = True,
    ) -> CaseInformationRequest:
        case = await self.session.get(ComplianceCase, case_id)
        if case is None:
            raise NotFoundError("Compliance case not found.")
        request = CaseInformationRequest(
            compliance_case_id=case.id,
            information_definition_id=information_definition_id,
            question_text=question_text[:4000],
            requested_from_actor=requested_from_actor,
            status=(
                CaseInformationRequestStatus.REQUESTED.value
                if requested_from_actor
                else CaseInformationRequestStatus.OPEN.value
            ),
            due_at=due_at,
            source_email_id=source_email_id,
            source_vendor_question=(source_vendor_question or None),
        )
        self.session.add(request)
        await self.session.flush()
        if requested_from_actor:
            await record_notification(
                self.session,
                information_request_alert(
                    request_id=request.id,
                    compliance_case_id=case.id,
                    recipient_actor=requested_from_actor,
                    severity="NORMAL",
                    overdue=False,
                ),
            )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="case_information_request",
            entity_id=request.id,
            action="information_request_created",
            after={"status": request.status},
        )
        if commit:
            await self.session.commit()
        return request

    async def update_information_request(
        self,
        request_id: uuid.UUID,
        *,
        actor: CurrentActor,
        status: str | None = None,
        requested_from_actor: str | None = None,
        response_value_id: uuid.UUID | None = None,
        resolution_note: str | None = None,
        commit: bool = True,
    ) -> CaseInformationRequest:
        request = await self.session.get(CaseInformationRequest, request_id)
        if request is None:
            raise NotFoundError("Information request not found.")
        before = {"status": request.status}
        if status is not None:
            if status not in {member.value for member in CaseInformationRequestStatus}:
                raise StateConflictError(f"Unknown request status {status!r}.")
            # An answer cannot be marked approved without a linked approved value.
            if status == CaseInformationRequestStatus.ANSWER_APPROVED.value and not (
                response_value_id or request.response_value_id
            ):
                raise StateConflictError(
                    "An approved answer must reference an approved information value."
                )
            request.status = status
            if status == CaseInformationRequestStatus.PROVIDED_TO_VENDOR.value:
                request.provided_to_vendor_at = utcnow()
        if requested_from_actor is not None:
            request.requested_from_actor = requested_from_actor
        if response_value_id is not None:
            request.response_value_id = response_value_id
        if resolution_note is not None:
            request.resolution_note = resolution_note[:2000]
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="case_information_request",
            entity_id=request.id,
            action="information_request_updated",
            before=before,
            after={"status": request.status},
        )
        if commit:
            await self.session.commit()
        return request

    async def refresh_metrics(self) -> None:
        open_cases = (
            await self.session.scalar(
                select(func.count())
                .select_from(ComplianceCase)
                .where(
                    ComplianceCase.status.not_in(
                        (CaseStatus.COMPLETED.value, CaseStatus.CANCELLED.value)
                    )
                )
            )
            or 0
        )
        blocked = (
            await self.session.scalar(
                select(func.count())
                .select_from(ComplianceCase)
                .where(ComplianceCase.status == CaseStatus.BLOCKED.value)
            )
            or 0
        )
        overdue = (
            await self.session.scalar(
                select(func.count())
                .select_from(ComplianceCase)
                .where(
                    ComplianceCase.status.not_in(
                        (CaseStatus.COMPLETED.value, CaseStatus.CANCELLED.value)
                    ),
                    ComplianceCase.statutory_due_date < utcnow().date(),
                )
            )
            or 0
        )
        open_requests = (
            await self.session.scalar(
                select(func.count())
                .select_from(CaseInformationRequest)
                .where(
                    CaseInformationRequest.status.in_(
                        (
                            CaseInformationRequestStatus.OPEN.value,
                            CaseInformationRequestStatus.REQUESTED.value,
                            CaseInformationRequestStatus.ANSWER_PROPOSED.value,
                            CaseInformationRequestStatus.ANSWER_REVIEW.value,
                        )
                    )
                )
            )
            or 0
        )
        COMPLIANCE_CASES_OPEN.set(open_cases)
        COMPLIANCE_CASES_BLOCKED.set(blocked)
        COMPLIANCE_CASES_OVERDUE.set(overdue)
        INFORMATION_REQUESTS_OPEN.set(open_requests)

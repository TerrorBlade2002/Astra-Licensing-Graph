"""Portal-run readiness, lifecycle, manifests, and pre-submission approval."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.browser.redaction import sanitize_portal_message
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import (
    PORTAL_RUNS_TOTAL,
    PORTAL_VALIDATION_ERRORS_TOTAL,
    PRE_SUBMISSION_REJECTIONS_TOTAL,
    PRE_SUBMISSION_SNAPSHOTS_TOTAL,
)
from app.documents.enums import ApprovalStatus, LifecycleStatus, StorageStatus
from app.forms.enums import FormInstanceStatus
from app.licensing.audit import add_licensing_audit
from app.licensing.enums import CaseStage
from app.models import (
    BrowserSession,
    ComplianceCase,
    Document,
    DocumentPacket,
    DocumentPacketItem,
    DocumentVersion,
    FormInstance,
    LicenseInventory,
    PortalAdapterVersion,
    PortalDefinition,
    PortalFieldMapping,
    PortalReviewVersion,
    PortalRun,
    PortalRunDocument,
    PortalRunField,
    PortalRunStep,
    PortalUserAuthorization,
    PreSubmissionSnapshot,
    UserPrincipal,
)
from app.models.mixins import utcnow
from app.packets.enums import INCLUDABLE_ITEM_STATUSES, PacketStatus
from app.portals.discrepancies import compare_field
from app.portals.enums import (
    ACTIVE_BROWSER_SESSION_STATUSES,
    AUTOMATION_LEVEL_RANK,
    AdapterStatus,
    AutomationLevel,
    PortalDocumentStatus,
    PortalFieldSourceType,
    PortalFieldStatus,
    PortalJobType,
    PortalReviewStatus,
    PortalRunStatus,
    PortalStepStatus,
    PortalStepType,
    SnapshotStatus,
)
from app.portals.policies import (
    action_is_allowed,
    approval_is_current,
    authorization_is_current,
)
from app.portals.snapshots import canonical_snapshot_hash
from app.repositories.portal_jobs import PortalJobRepository

_READY_FORM_STATUSES = {
    FormInstanceStatus.APPROVED_FOR_SIGNATURE.value,
    FormInstanceStatus.SIGNATURE_PENDING.value,
    FormInstanceStatus.SIGNED.value,
    FormInstanceStatus.READY_FOR_SUBMISSION.value,
}
_TERMINAL_RUN_STATUSES = {
    PortalRunStatus.COMPLETED.value,
    PortalRunStatus.CANCELLED.value,
    PortalRunStatus.SUBMITTED.value,
}
_HUMAN_ONLY_SOURCES = {
    PortalFieldSourceType.MANUAL_OPERATOR_INPUT.value,
    PortalFieldSourceType.ATTESTATION.value,
    PortalFieldSourceType.SIGNATURE.value,
    PortalFieldSourceType.PAYMENT.value,
}


class PortalRunService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def create_run(
        self,
        case_id: uuid.UUID,
        *,
        actor: CurrentActor,
        fields: dict[str, Any],
    ) -> PortalRun:
        case = await self.session.get(ComplianceCase, case_id)
        if case is None:
            raise NotFoundError("Compliance case not found.")
        if case.current_stage != CaseStage.SUBMISSION_PENDING.value:
            raise StateConflictError(
                "Portal assistance requires the compliance case to reach SUBMISSION_PENDING."
            )
        portal = await self._portal(fields["portal_definition_id"])
        review = await self._current_review(portal.id)
        self._assert_review_scope(
            portal=portal,
            review=review,
            filing_type=fields["filing_type"],
            legal_entity_id=case.legal_entity_id,
        )
        level = fields.get("automation_level") or self.settings.portal_default_automation_level
        if level not in AUTOMATION_LEVEL_RANK:
            raise StateConflictError("Unknown portal automation level.")
        if AUTOMATION_LEVEL_RANK[level] > AUTOMATION_LEVEL_RANK[portal.approved_automation_level]:
            raise StateConflictError("Run exceeds the portal's approved automation level.")
        if fields.get("license_id") and fields["license_id"] != case.license_id:
            raise StateConflictError("Run license does not match the compliance case.")
        license_record = (
            await self.session.get(LicenseInventory, fields["license_id"])
            if fields.get("license_id")
            else None
        )
        if license_record and license_record.legal_entity_id != case.legal_entity_id:
            raise StateConflictError("Run license belongs to another legal entity.")

        form = await self._validate_form(case, fields.get("form_instance_id"))
        packet = await self._validate_packet(case, fields.get("document_packet_id"))
        adapter = await self._active_adapter(portal.id, required=level != "PREPARE_ONLY")
        if fields.get("assigned_operator_id"):
            await self._assert_user_authorized(
                portal=portal,
                user_id=fields["assigned_operator_id"],
                filing_type=fields["filing_type"],
                legal_entity_id=case.legal_entity_id,
            )
        for user_field in ("assigned_signatory_id", "assigned_payment_approver_id"):
            if fields.get(user_field) and not await self.session.get(
                UserPrincipal, fields[user_field]
            ):
                raise NotFoundError(f"{user_field.replace('_', ' ').title()} not found.")

        run = PortalRun(
            run_key=f"portal-{case.case_key}-{uuid.uuid4().hex[:8]}"[:120],
            portal_definition_id=portal.id,
            portal_review_version_id=review.id,
            portal_adapter_version_id=adapter.id if adapter else None,
            compliance_case_id=case.id,
            legal_entity_id=case.legal_entity_id,
            license_id=fields.get("license_id") or case.license_id,
            form_instance_id=form.id if form else None,
            document_packet_id=packet.id if packet else None,
            filing_type=fields["filing_type"],
            automation_level=level,
            status=PortalRunStatus.READY.value,
            current_stage=PortalRunStatus.READY.value,
            assigned_operator_id=fields.get("assigned_operator_id"),
            assigned_signatory_id=fields.get("assigned_signatory_id"),
            assigned_payment_approver_id=fields.get("assigned_payment_approver_id"),
            earliest_start_at=fields.get("earliest_start_at"),
            deadline_at=fields.get("deadline_at"),
            created_by_actor=actor.actor_id,
        )
        self.session.add(run)
        await self.session.flush()
        await self._initialize_fields(run, adapter)
        await self._initialize_documents(run, packet, actor)
        await self._add_step(
            run,
            step_type=PortalStepType.NAVIGATE.value,
            status=PortalStepStatus.PENDING.value,
            result_summary="Portal run created after governed-input readiness checks.",
        )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_run",
            entity_id=run.id,
            action="portal_run_created",
            after={
                "portal_id": str(portal.id),
                "filing_type": run.filing_type,
                "automation_level": run.automation_level,
                "status": run.status,
            },
        )
        await self.session.commit()
        PORTAL_RUNS_TOTAL.inc()
        return run

    async def update_run(
        self, run_id: uuid.UUID, *, actor: CurrentActor, changes: dict[str, Any]
    ) -> PortalRun:
        run = await self._run(run_id)
        if run.status in _TERMINAL_RUN_STATUSES:
            raise StateConflictError("A terminal portal run cannot be edited.")
        portal = await self._portal(run.portal_definition_id)
        if changes.get("assigned_operator_id"):
            await self._assert_user_authorized(
                portal=portal,
                user_id=changes["assigned_operator_id"],
                filing_type=run.filing_type,
                legal_entity_id=run.legal_entity_id,
            )
            active_session = await self.session.scalar(
                select(BrowserSession.id).where(
                    BrowserSession.portal_run_id == run.id,
                    BrowserSession.session_status.in_(ACTIVE_BROWSER_SESSION_STATUSES),
                )
            )
            if active_session and changes["assigned_operator_id"] != run.assigned_operator_id:
                raise StateConflictError(
                    "Close the current browser session before reassigning the operator."
                )
        before = {field: getattr(run, field) for field in changes}
        for field, value in changes.items():
            setattr(run, field, value)
        await self._invalidate_snapshot(run, actor=actor, reason="Portal run assignment changed.")
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_run",
            entity_id=run.id,
            action="portal_run_updated",
            before=before,
            after={field: getattr(run, field) for field in changes},
        )
        await self.session.commit()
        return run

    async def start(self, run_id: uuid.UUID, *, actor: CurrentActor) -> PortalRun:
        run = await self._run(run_id)
        if run.status not in {
            PortalRunStatus.READY.value,
            PortalRunStatus.WAITING_OPERATOR.value,
        }:
            raise StateConflictError("Portal run is not ready to start.")
        portal, _review = await self.revalidate_governance(run)
        if run.automation_level == AutomationLevel.PREPARE_ONLY.value:
            run.status = PortalRunStatus.WAITING_OPERATOR.value
            run.current_stage = PortalRunStatus.WAITING_OPERATOR.value
            await self.session.commit()
            return run
        if not self.settings.portal_automation_enabled or not (
            self.settings.browser_automation_enabled
        ):
            raise StateConflictError("Portal browser assistance is disabled by configuration.")
        if run.assigned_operator_id is None:
            run.status = PortalRunStatus.WAITING_OPERATOR.value
            run.current_stage = PortalRunStatus.WAITING_OPERATOR.value
            await self.session.commit()
            return run
        await self._assert_actor_is_user(actor, run.assigned_operator_id)
        await self._assert_user_authorized(
            portal=portal,
            user_id=run.assigned_operator_id,
            filing_type=run.filing_type,
            legal_entity_id=run.legal_entity_id,
        )
        run.status = PortalRunStatus.WAITING_OPERATOR.value
        run.current_stage = PortalRunStatus.WAITING_OPERATOR.value
        run.started_at = run.started_at or utcnow()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_run",
            entity_id=run.id,
            action="portal_run_started",
            after={"status": run.status},
        )
        await self.session.commit()
        return run

    async def pause(self, run_id: uuid.UUID, *, actor: CurrentActor) -> PortalRun:
        run = await self._run(run_id)
        if run.status in _TERMINAL_RUN_STATUSES:
            raise StateConflictError("Terminal portal run cannot be paused.")
        run.status = PortalRunStatus.BLOCKED.value
        run.current_stage = PortalRunStatus.BLOCKED.value
        run.last_error_code = "operator_paused"
        run.last_error_message = "Paused by an authorized operator."
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_run",
            entity_id=run.id,
            action="portal_run_paused",
        )
        await self.session.commit()
        return run

    async def queue_navigation(
        self,
        run_id: uuid.UUID,
        *,
        actor: CurrentActor,
        route_key: str,
        request_id: uuid.UUID,
    ) -> PortalRun:
        run = await self._run(run_id)
        portal, review = await self.revalidate_governance(run)
        if run.assigned_operator_id is None:
            raise StateConflictError("Portal run has no assigned operator.")
        await self._assert_actor_is_user(actor, run.assigned_operator_id)
        decision = action_is_allowed(
            action="NAVIGATE",
            run_level=run.automation_level,
            portal_level=portal.approved_automation_level,
            allowed_actions=review.allowed_actions,
            prohibited_actions=review.prohibited_actions,
        )
        if not decision.allowed:
            raise StateConflictError(decision.reason)
        if run.portal_adapter_version_id is None:
            raise StateConflictError("Portal run has no reviewed adapter.")
        adapter = await self.session.get(PortalAdapterVersion, run.portal_adapter_version_id)
        route = adapter.supported_routes.get(route_key) if adapter else None
        if not isinstance(route, dict) or not isinstance(route.get("url"), str):
            raise StateConflictError("Requested filing route is not in the reviewed adapter.")
        browser_session = await self.active_browser_session(run, actor=actor)
        await PortalJobRepository(self.session).enqueue(
            job_type=PortalJobType.NAVIGATE_PORTAL,
            idempotency_key=(
                f"portal-navigate:{run.id}:{browser_session.id}:{route_key}:{request_id}"
            ),
            portal_run_id=run.id,
            browser_session_id=browser_session.id,
            payload={"route_key": route_key, "route": route},
            max_attempts=2,
        )
        await self.session.commit()
        return run

    async def queue_validation(self, run_id: uuid.UUID, *, actor: CurrentActor) -> PortalRun:
        run = await self._run(run_id)
        portal, review = await self.revalidate_governance(run)
        decision = action_is_allowed(
            action="VALIDATE",
            run_level=run.automation_level,
            portal_level=portal.approved_automation_level,
            allowed_actions=review.allowed_actions,
            prohibited_actions=review.prohibited_actions,
        )
        if not decision.allowed:
            raise StateConflictError(decision.reason)
        browser_session = await self.active_browser_session(run, actor=actor)
        await PortalJobRepository(self.session).enqueue(
            job_type=PortalJobType.RUN_PORTAL_VALIDATION,
            idempotency_key=f"portal-validation:{run.id}:{uuid.uuid4().hex}",
            portal_run_id=run.id,
            browser_session_id=browser_session.id,
            max_attempts=2,
        )
        await self.session.commit()
        return run

    async def active_browser_session(
        self, run: PortalRun, *, actor: CurrentActor
    ) -> BrowserSession:
        if run.assigned_operator_id is None:
            raise StateConflictError("Portal run has no assigned operator.")
        await self._assert_actor_is_user(actor, run.assigned_operator_id)
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
            raise StateConflictError("No current operator-owned browser session is available.")
        return browser_session

    async def resume(self, run_id: uuid.UUID, *, actor: CurrentActor) -> PortalRun:
        run = await self._run(run_id)
        if run.status != PortalRunStatus.BLOCKED.value:
            raise StateConflictError("Only a blocked portal run can resume.")
        await self.revalidate_governance(run)
        if run.assigned_operator_id:
            await self._assert_actor_is_user(actor, run.assigned_operator_id)
        browser_session = await self.session.scalar(
            select(BrowserSession)
            .where(
                BrowserSession.portal_run_id == run.id,
                BrowserSession.session_status.in_(ACTIVE_BROWSER_SESSION_STATUSES),
            )
            .order_by(BrowserSession.started_at.desc())
        )
        if browser_session is None:
            run.status = PortalRunStatus.WAITING_OPERATOR.value
            run.current_stage = run.status
            run.last_error_code = None
            run.last_error_message = None
            await self.session.commit()
            return run
        run.status = PortalRunStatus.SESSION_ACTIVE.value
        run.current_stage = PortalRunStatus.SESSION_ACTIVE.value
        run.last_error_code = None
        run.last_error_message = None
        await PortalJobRepository(self.session).enqueue(
            job_type=PortalJobType.RECONCILE_SESSION,
            idempotency_key=f"portal-resume:{run.id}:{uuid.uuid4().hex}",
            portal_run_id=run.id,
            browser_session_id=browser_session.id,
            max_attempts=1,
        )
        await self.session.commit()
        return run

    async def cancel(self, run_id: uuid.UUID, *, actor: CurrentActor) -> PortalRun:
        run = await self._run(run_id)
        if run.status == PortalRunStatus.SUBMITTED.value:
            raise StateConflictError("A submitted run cannot be cancelled.")
        run.status = PortalRunStatus.CANCELLED.value
        run.current_stage = PortalRunStatus.CANCELLED.value
        run.completed_at = utcnow()
        await PortalJobRepository(self.session).cancel_pending_for_run(run.id)
        sessions = list(
            await self.session.scalars(
                select(BrowserSession).where(
                    BrowserSession.portal_run_id == run.id,
                    BrowserSession.session_status.in_(ACTIVE_BROWSER_SESSION_STATUSES),
                )
            )
        )
        for browser_session in sessions:
            await PortalJobRepository(self.session).enqueue(
                job_type=PortalJobType.CLOSE_BROWSER_SESSION,
                idempotency_key=f"portal-close:{browser_session.id}",
                portal_run_id=run.id,
                browser_session_id=browser_session.id,
                max_attempts=3,
            )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_run",
            entity_id=run.id,
            action="portal_run_cancelled",
        )
        await self.session.commit()
        return run

    async def capture_validation(
        self,
        run_id: uuid.UUID,
        *,
        actor: CurrentActor,
        messages: list[dict[str, Any]],
        observed_page_category: str,
    ) -> PortalRun:
        run = await self._run(run_id)
        await self._invalidate_snapshot(run, actor=actor, reason="Portal validation recaptured.")
        safe_messages = [
            {
                "code": str(message.get("code", "PORTAL_VALIDATION"))[:120],
                "category": str(message.get("category", "GENERAL"))[:120],
                "message": sanitize_portal_message(message.get("message", "")),
                "blocking": bool(message.get("blocking", True)),
                "field_key": (
                    str(message["field_key"])[:120] if message.get("field_key") else None
                ),
            }
            for message in messages[:200]
        ]
        await self._add_step(
            run,
            step_type=PortalStepType.VALIDATION.value,
            status=PortalStepStatus.COMPLETED.value,
            page_category=observed_page_category,
            observed_state={"messages": safe_messages},
            result_summary=f"Captured {len(safe_messages)} portal validation messages.",
        )
        run.status = (
            PortalRunStatus.DISCREPANCIES_FOUND.value
            if any(item["blocking"] for item in safe_messages)
            else PortalRunStatus.READY_FOR_PRE_SUBMISSION_REVIEW.value
        )
        run.current_stage = run.status
        await self.session.commit()
        PORTAL_VALIDATION_ERRORS_TOTAL.inc(sum(1 for item in safe_messages if item["blocking"]))
        return run

    async def create_snapshot(
        self, run_id: uuid.UUID, *, actor: CurrentActor
    ) -> PreSubmissionSnapshot:
        run = await self._run(run_id)
        await self.revalidate_governance(run)
        fields = list(
            await self.session.scalars(
                select(PortalRunField)
                .where(PortalRunField.portal_run_id == run.id)
                .order_by(PortalRunField.portal_field_key)
            )
        )
        documents = list(
            await self.session.scalars(
                select(PortalRunDocument)
                .where(PortalRunDocument.portal_run_id == run.id)
                .order_by(PortalRunDocument.expected_filename)
            )
        )
        mappings = {
            mapping.id: mapping
            for mapping in await self.session.scalars(
                select(PortalFieldMapping).where(
                    PortalFieldMapping.id.in_(
                        [
                            row.portal_field_mapping_id
                            for row in fields
                            if row.portal_field_mapping_id
                        ]
                    )
                )
            )
        }
        discrepancies: list[dict[str, Any]] = []
        field_manifest: list[dict[str, Any]] = []
        for field_row in fields:
            mapping = (
                mappings.get(field_row.portal_field_mapping_id)
                if field_row.portal_field_mapping_id
                else None
            )
            if field_row.status == PortalFieldStatus.DISCREPANCY.value:
                discrepancies.append(
                    {
                        "code": field_row.discrepancy_code or "VALUE_MISMATCH",
                        "field_key": field_row.portal_field_key,
                        "blocking": True,
                    }
                )
            pure = compare_field(
                field_key=field_row.portal_field_key,
                approved_fingerprint=field_row.approved_value_fingerprint,
                entered_fingerprint=field_row.entered_value_fingerprint,
                required=bool(mapping and mapping.required and not mapping.human_only),
            )
            if pure:
                discrepancies.append(pure)
            field_manifest.append(
                {
                    "field_key": field_row.portal_field_key,
                    "source_type": field_row.approved_source_type,
                    "source_record_id": (
                        str(field_row.approved_source_record_id)
                        if field_row.approved_source_record_id
                        else None
                    ),
                    "approved_fingerprint": field_row.approved_value_fingerprint,
                    "entered_fingerprint": field_row.entered_value_fingerprint,
                    "status": field_row.status,
                    "human_only": bool(mapping and mapping.human_only),
                }
            )
        document_manifest: list[dict[str, Any]] = []
        for document_row in documents:
            if document_row.status != PortalDocumentStatus.VERIFIED.value:
                discrepancies.append(
                    {
                        "code": "DOCUMENT_MISSING",
                        "document_id": str(document_row.document_id),
                        "blocking": True,
                    }
                )
            document_manifest.append(
                {
                    "document_id": str(document_row.document_id),
                    "document_version_id": str(document_row.document_version_id),
                    "expected_sha256": document_row.expected_sha256,
                    "expected_filename": document_row.expected_filename,
                    "portal_display_name": document_row.portal_display_name,
                    "portal_size_bytes": document_row.portal_size_bytes,
                    "status": document_row.status,
                }
            )
        validation_messages = await self._latest_validation_messages(run.id)
        discrepancies.extend(
            {
                "code": "PORTAL_VALIDATION_ERROR",
                "message": message.get("message"),
                "blocking": True,
            }
            for message in validation_messages
            if message.get("blocking")
        )
        version = (
            await self.session.scalar(
                select(func.max(PreSubmissionSnapshot.version)).where(
                    PreSubmissionSnapshot.portal_run_id == run.id
                )
            )
            or 0
        ) + 1
        form = (
            await self.session.get(FormInstance, run.form_instance_id)
            if run.form_instance_id
            else None
        )
        payload = {
            "portal_definition_id": str(run.portal_definition_id),
            "portal_review_version_id": str(run.portal_review_version_id),
            "portal_adapter_version_id": (
                str(run.portal_adapter_version_id) if run.portal_adapter_version_id else None
            ),
            "legal_entity_id": str(run.legal_entity_id),
            "compliance_case_id": str(run.compliance_case_id),
            "filing_type": run.filing_type,
            "form_instance_version": form.version if form else None,
            "field_manifest": field_manifest,
            "document_manifest": document_manifest,
            "portal_validation_messages": validation_messages,
            "discrepancy_report": discrepancies,
        }
        snapshot = PreSubmissionSnapshot(
            portal_run_id=run.id,
            version=version,
            form_instance_version=form.version if form else None,
            field_manifest=field_manifest,
            document_manifest=document_manifest,
            portal_validation_messages=validation_messages,
            discrepancy_report=discrepancies,
            screenshot_manifest=[],
            snapshot_sha256=canonical_snapshot_hash(payload),
            status=(
                SnapshotStatus.DISCREPANCIES_FOUND.value
                if discrepancies
                else SnapshotStatus.READY_FOR_REVIEW.value
            ),
            created_by_actor=actor.actor_id,
        )
        self.session.add(snapshot)
        run.status = (
            PortalRunStatus.DISCREPANCIES_FOUND.value
            if discrepancies
            else PortalRunStatus.READY_FOR_PRE_SUBMISSION_REVIEW.value
        )
        run.current_stage = run.status
        await self._add_step(
            run,
            step_type=PortalStepType.PRE_SUBMISSION_CAPTURE.value,
            status=PortalStepStatus.COMPLETED.value,
            result_summary=f"Snapshot v{version} captured with {len(discrepancies)} blockers.",
        )
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="pre_submission_snapshot",
            entity_id=snapshot.id,
            action="pre_submission_snapshot_created",
            after={
                "version": snapshot.version,
                "status": snapshot.status,
                "blocker_count": len(discrepancies),
            },
        )
        await self.session.commit()
        PRE_SUBMISSION_SNAPSHOTS_TOTAL.inc()
        return snapshot

    async def approve_snapshot(
        self, snapshot_id: uuid.UUID, *, actor: CurrentActor
    ) -> PreSubmissionSnapshot:
        snapshot = await self.session.get(PreSubmissionSnapshot, snapshot_id)
        if snapshot is None:
            raise NotFoundError("Pre-submission snapshot not found.")
        if snapshot.status != SnapshotStatus.READY_FOR_REVIEW.value:
            raise StateConflictError("Only a blocker-free snapshot can be approved.")
        if snapshot.created_by_actor == actor.actor_id:
            raise StateConflictError("Snapshot creator cannot approve the same snapshot.")
        run = await self._run(snapshot.portal_run_id)
        await self.revalidate_governance(run)
        latest = await self.session.scalar(
            select(PreSubmissionSnapshot)
            .where(PreSubmissionSnapshot.portal_run_id == run.id)
            .order_by(PreSubmissionSnapshot.version.desc())
        )
        if latest is None or latest.id != snapshot.id:
            raise StateConflictError("Only the latest pre-submission snapshot can be approved.")
        expected = canonical_snapshot_hash(
            {
                "portal_definition_id": str(run.portal_definition_id),
                "portal_review_version_id": str(run.portal_review_version_id),
                "portal_adapter_version_id": (
                    str(run.portal_adapter_version_id) if run.portal_adapter_version_id else None
                ),
                "legal_entity_id": str(run.legal_entity_id),
                "compliance_case_id": str(run.compliance_case_id),
                "filing_type": run.filing_type,
                "form_instance_version": snapshot.form_instance_version,
                "field_manifest": snapshot.field_manifest,
                "document_manifest": snapshot.document_manifest,
                "portal_validation_messages": snapshot.portal_validation_messages,
                "discrepancy_report": snapshot.discrepancy_report,
            }
        )
        if expected != snapshot.snapshot_sha256:
            raise StateConflictError("Snapshot hash no longer matches its approved-data manifest.")
        snapshot.status = SnapshotStatus.APPROVED.value
        snapshot.reviewed_by_actor = actor.actor_id
        snapshot.reviewed_at = utcnow()
        run.status = PortalRunStatus.PRE_SUBMISSION_APPROVED.value
        run.current_stage = PortalRunStatus.PRE_SUBMISSION_APPROVED.value
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="pre_submission_snapshot",
            entity_id=snapshot.id,
            action="pre_submission_snapshot_approved",
            after={"version": snapshot.version, "snapshot_sha256": snapshot.snapshot_sha256},
        )
        await self.session.commit()
        return snapshot

    async def reject_snapshot(
        self, snapshot_id: uuid.UUID, *, actor: CurrentActor, reason: str | None
    ) -> PreSubmissionSnapshot:
        snapshot = await self.session.get(PreSubmissionSnapshot, snapshot_id)
        if snapshot is None:
            raise NotFoundError("Pre-submission snapshot not found.")
        if snapshot.status not in {
            SnapshotStatus.READY_FOR_REVIEW.value,
            SnapshotStatus.DISCREPANCIES_FOUND.value,
        }:
            raise StateConflictError("Snapshot cannot be rejected from its current state.")
        snapshot.status = SnapshotStatus.REJECTED.value
        snapshot.reviewed_by_actor = actor.actor_id
        snapshot.reviewed_at = utcnow()
        run = await self._run(snapshot.portal_run_id)
        run.status = PortalRunStatus.DISCREPANCIES_FOUND.value
        run.current_stage = run.status
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="pre_submission_snapshot",
            entity_id=snapshot.id,
            action="pre_submission_snapshot_rejected",
            metadata={"reason": (reason or "")[:500]},
        )
        await self.session.commit()
        PRE_SUBMISSION_REJECTIONS_TOTAL.inc()
        return snapshot

    async def revalidate_governance(
        self, run: PortalRun
    ) -> tuple[PortalDefinition, PortalReviewVersion]:
        portal = await self._portal(run.portal_definition_id)
        review = await self.session.get(PortalReviewVersion, run.portal_review_version_id)
        if review is None:
            raise StateConflictError("Pinned portal review no longer exists.")
        decision = approval_is_current(
            portal_status=portal.status,
            review_status=review.status,
            valid_from=review.valid_from,
            valid_to=review.valid_to,
            terms_expires_at=portal.terms_review_expires_at,
        )
        if not decision.allowed:
            run.status = PortalRunStatus.FAILED_REVIEW.value
            run.current_stage = run.status
            run.last_error_code = "portal_review_invalid"
            run.last_error_message = decision.reason
            raise StateConflictError(decision.reason)
        if run.filing_type not in review.approved_filing_types:
            raise StateConflictError("Pinned review does not approve this filing type.")
        if review.approved_entity_ids and run.legal_entity_id not in review.approved_entity_ids:
            raise StateConflictError("Pinned review does not approve this legal entity.")
        if run.portal_adapter_version_id:
            adapter = await self.session.get(PortalAdapterVersion, run.portal_adapter_version_id)
            if adapter is None or adapter.status != AdapterStatus.ACTIVE.value:
                raise StateConflictError("Pinned portal adapter is no longer active.")
        return portal, review

    async def _initialize_fields(
        self, run: PortalRun, adapter: PortalAdapterVersion | None
    ) -> None:
        if adapter is None:
            return
        mappings = list(
            await self.session.scalars(
                select(PortalFieldMapping)
                .where(
                    PortalFieldMapping.portal_adapter_version_id == adapter.id,
                    PortalFieldMapping.filing_type == run.filing_type,
                )
                .order_by(PortalFieldMapping.sort_order)
            )
        )
        for mapping in mappings:
            self.session.add(
                PortalRunField(
                    portal_run_id=run.id,
                    portal_field_mapping_id=mapping.id,
                    portal_field_key=mapping.portal_field_key,
                    label=mapping.portal_label,
                    approved_source_type=mapping.source_type,
                    status=(
                        PortalFieldStatus.HUMAN_ONLY.value
                        if mapping.human_only or mapping.source_type in _HUMAN_ONLY_SOURCES
                        else PortalFieldStatus.PENDING.value
                    ),
                )
            )

    async def _initialize_documents(
        self,
        run: PortalRun,
        packet: DocumentPacket | None,
        actor: CurrentActor,
    ) -> None:
        if packet is None:
            return
        items = list(
            await self.session.scalars(
                select(DocumentPacketItem)
                .where(
                    DocumentPacketItem.document_packet_id == packet.id,
                    DocumentPacketItem.status.in_(INCLUDABLE_ITEM_STATUSES),
                )
                .order_by(DocumentPacketItem.sort_order)
            )
        )
        for item in items:
            if not item.document_id or not item.document_version_id:
                raise StateConflictError("Approved packet contains an unresolved document item.")
            document = await self.session.get(Document, item.document_id)
            version = await self.session.get(DocumentVersion, item.document_version_id)
            if document is None or version is None:
                raise StateConflictError("Approved packet document is missing.")
            if (
                document.approval_status != ApprovalStatus.APPROVED.value
                or document.lifecycle_status != LifecycleStatus.ACTIVE.value
                or document.current_version_id != version.id
                or version.storage_status != StorageStatus.AVAILABLE.value
                or version.content_sha256 != item.document_sha256
                or document.content_sha256 != item.document_sha256
                or (document.expiry_date and document.expiry_date < date.today())
            ):
                raise StateConflictError(
                    "Packet contains an unapproved, expired, unavailable, superseded, or "
                    "hash-invalid document."
                )
            self.session.add(
                PortalRunDocument(
                    portal_run_id=run.id,
                    document_id=document.id,
                    document_version_id=version.id,
                    expected_filename=item.filename_in_archive or version.filename,
                    expected_sha256=version.content_sha256,
                    portal_document_category=item.document_type,
                    status=PortalDocumentStatus.VALIDATED.value,
                    selected_by_actor=actor.actor_id,
                )
            )

    async def _validate_form(
        self, case: ComplianceCase, form_id: uuid.UUID | None
    ) -> FormInstance | None:
        if form_id is None:
            return None
        form = await self.session.get(FormInstance, form_id)
        if form is None:
            raise NotFoundError("Form instance not found.")
        if form.compliance_case_id != case.id or form.status not in _READY_FORM_STATUSES:
            raise StateConflictError("Form is not approved and ready for this compliance case.")
        if form.signature_required and form.status not in {
            FormInstanceStatus.SIGNED.value,
            FormInstanceStatus.READY_FOR_SUBMISSION.value,
        }:
            raise StateConflictError("Signature-required form has no approved signed evidence.")
        return form

    async def _validate_packet(
        self, case: ComplianceCase, packet_id: uuid.UUID | None
    ) -> DocumentPacket | None:
        if packet_id is None:
            return None
        packet = await self.session.get(DocumentPacket, packet_id)
        if packet is None:
            raise NotFoundError("Document packet not found.")
        if packet.compliance_case_id != case.id or packet.status != PacketStatus.APPROVED.value:
            raise StateConflictError("Packet is not approved for this compliance case.")
        if packet.missing_items or packet.validation_results:
            raise StateConflictError("Packet still contains missing items or validation findings.")
        return packet

    async def _active_adapter(
        self, portal_id: uuid.UUID, *, required: bool
    ) -> PortalAdapterVersion | None:
        adapter = await self.session.scalar(
            select(PortalAdapterVersion).where(
                PortalAdapterVersion.portal_definition_id == portal_id,
                PortalAdapterVersion.status == AdapterStatus.ACTIVE.value,
            )
        )
        if required and adapter is None:
            raise StateConflictError("Portal has no active reviewed adapter.")
        return adapter

    async def _assert_user_authorized(
        self,
        *,
        portal: PortalDefinition,
        user_id: uuid.UUID,
        filing_type: str,
        legal_entity_id: uuid.UUID,
    ) -> PortalUserAuthorization:
        authorization = await self.session.scalar(
            select(PortalUserAuthorization).where(
                PortalUserAuthorization.portal_definition_id == portal.id,
                PortalUserAuthorization.user_principal_id == user_id,
            )
        )
        if authorization is None:
            raise StateConflictError("User has no portal authorization.")
        decision = authorization_is_current(
            status=authorization.authorization_status,
            expires_at=authorization.expires_at,
            filing_type=filing_type,
            legal_entity_id=legal_entity_id,
            authorized_filing_types=authorization.authorized_filing_types,
            authorized_entity_ids=authorization.authorized_entity_ids,
        )
        if not decision.allowed:
            raise StateConflictError(decision.reason)
        return authorization

    async def _assert_actor_is_user(self, actor: CurrentActor, expected_user_id: uuid.UUID) -> None:
        principal = await self.session.scalar(
            select(UserPrincipal).where(
                UserPrincipal.tenant_id == actor.tenant_id,
                UserPrincipal.object_id == actor.object_id,
            )
        )
        if principal is None or principal.id != expected_user_id:
            raise StateConflictError(
                "Authenticated actor does not own the assigned portal session."
            )

    @staticmethod
    def _assert_review_scope(
        *,
        portal: PortalDefinition,
        review: PortalReviewVersion,
        filing_type: str,
        legal_entity_id: uuid.UUID,
    ) -> None:
        decision = approval_is_current(
            portal_status=portal.status,
            review_status=review.status,
            valid_from=review.valid_from,
            valid_to=review.valid_to,
            terms_expires_at=portal.terms_review_expires_at,
        )
        if not decision.allowed:
            raise StateConflictError(decision.reason)
        if filing_type not in portal.supported_filing_types:
            raise StateConflictError("Portal does not support this filing type.")
        if filing_type not in review.approved_filing_types:
            raise StateConflictError("Current portal review does not approve this filing type.")
        if review.approved_entity_ids and legal_entity_id not in review.approved_entity_ids:
            raise StateConflictError("Current portal review does not approve this legal entity.")

    async def _latest_validation_messages(self, run_id: uuid.UUID) -> list[dict[str, Any]]:
        step = await self.session.scalar(
            select(PortalRunStep)
            .where(
                PortalRunStep.portal_run_id == run_id,
                PortalRunStep.step_type == PortalStepType.VALIDATION.value,
            )
            .order_by(PortalRunStep.sequence_number.desc())
        )
        if not step or not step.observed_state:
            return []
        messages = step.observed_state.get("messages", [])
        return messages if isinstance(messages, list) else []

    async def _add_step(
        self,
        run: PortalRun,
        *,
        step_type: str,
        status: str,
        page_category: str | None = None,
        observed_state: dict[str, Any] | None = None,
        result_summary: str | None = None,
    ) -> PortalRunStep:
        sequence = (
            await self.session.scalar(
                select(func.max(PortalRunStep.sequence_number)).where(
                    PortalRunStep.portal_run_id == run.id
                )
            )
            or 0
        ) + 1
        step = PortalRunStep(
            portal_run_id=run.id,
            step_key=f"{step_type.lower()}-{sequence}",
            sequence_number=sequence,
            step_type=step_type,
            status=status,
            automation_mode=run.automation_level,
            page_category=page_category,
            observed_state=observed_state,
            result_summary=result_summary,
            started_at=utcnow(),
            completed_at=(utcnow() if status == PortalStepStatus.COMPLETED.value else None),
        )
        self.session.add(step)
        return step

    async def _invalidate_snapshot(
        self, run: PortalRun, *, actor: CurrentActor, reason: str
    ) -> None:
        approved = await self.session.scalar(
            select(PreSubmissionSnapshot).where(
                PreSubmissionSnapshot.portal_run_id == run.id,
                PreSubmissionSnapshot.status == SnapshotStatus.APPROVED.value,
            )
        )
        if approved:
            approved.status = SnapshotStatus.SUPERSEDED.value
            run.status = PortalRunStatus.DISCREPANCIES_FOUND.value
            run.current_stage = run.status
            add_licensing_audit(
                self.session,
                actor=actor,
                entity_type="pre_submission_snapshot",
                entity_id=approved.id,
                action="pre_submission_snapshot_invalidated",
                metadata={"reason": reason[:500]},
            )

    async def _portal(self, portal_id: uuid.UUID) -> PortalDefinition:
        portal = await self.session.get(PortalDefinition, portal_id)
        if portal is None:
            raise NotFoundError("Portal not found.")
        return portal

    async def _current_review(self, portal_id: uuid.UUID) -> PortalReviewVersion:
        review = await self.session.scalar(
            select(PortalReviewVersion).where(
                PortalReviewVersion.portal_definition_id == portal_id,
                PortalReviewVersion.status == PortalReviewStatus.APPROVED.value,
            )
        )
        if review is None:
            raise StateConflictError("Portal has no active approved review.")
        return review

    async def _run(self, run_id: uuid.UUID) -> PortalRun:
        run = await self.session.get(PortalRun, run_id)
        if run is None:
            raise NotFoundError("Portal run not found.")
        return run

"""Reviewed field-entry and governed document-upload coordination."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.config import Settings
from app.core.crypto import EncryptionUnavailableError, build_cipher, content_sha256
from app.core.exceptions import NotFoundError, StateConflictError
from app.documents.enums import ApprovalStatus, LifecycleStatus, StorageStatus
from app.forms.enums import FormFieldValueStatus
from app.licensing.audit import add_licensing_audit
from app.models import (
    ComplianceCase,
    Document,
    DocumentVersion,
    FormFieldValue,
    FormTemplateField,
    InformationDefinition,
    InformationValue,
    LegalEntity,
    LicenseInventory,
    PortalFieldMapping,
    PortalRun,
    PortalRunDocument,
    PortalRunField,
    PreSubmissionSnapshot,
)
from app.models.mixins import utcnow
from app.portals.enums import (
    PortalDocumentStatus,
    PortalFieldSourceType,
    PortalFieldStatus,
    PortalJobType,
    PortalRunStatus,
    SnapshotStatus,
)
from app.portals.policies import action_is_allowed
from app.portals.snapshots import redact_display
from app.repositories.portal_jobs import PortalJobRepository
from app.services.portal_run_service import PortalRunService

_ALLOWED_ENTITY_FIELDS = {
    "legal_name",
    "display_name",
    "formation_jurisdiction",
    "formation_date",
    "nmls_id",
    "primary_business_address",
    "mailing_address",
}
_ALLOWED_LICENSE_FIELDS = {
    "license_number",
    "nmls_license_id",
    "filing_channel",
    "issue_date",
    "effective_date",
    "expiration_date",
    "renewal_due_date",
}
_ALLOWED_CASE_FIELDS = {
    "case_key",
    "case_type",
    "statutory_due_date",
    "internal_target_date",
}
_TRANSFORMS = {
    None: lambda value: value,
    "UPPERCASE": lambda value: str(value).upper(),
    "LOWERCASE": lambda value: str(value).lower(),
    "TRIM": lambda value: str(value).strip(),
    "DATE_MMDDYYYY": lambda value: (
        value.strftime("%m/%d/%Y") if hasattr(value, "strftime") else str(value)
    ),
    "BOOLEAN_YES_NO": lambda value: "Yes" if bool(value) else "No",
}


@dataclass(frozen=True)
class ResolvedPortalField:
    run_field_id: uuid.UUID
    field_key: str
    value: str
    fingerprint: str
    sensitive: bool


class PortalEntryService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def queue_field_entry(self, run_id: uuid.UUID, *, actor: CurrentActor) -> PortalRun:
        run = await self._run(run_id)
        run_service = PortalRunService(self.session, self.settings)
        portal, review = await run_service.revalidate_governance(run)
        decision = action_is_allowed(
            action="ENTER_FIELD",
            run_level=run.automation_level,
            portal_level=portal.approved_automation_level,
            allowed_actions=review.allowed_actions,
            prohibited_actions=review.prohibited_actions,
        )
        if not decision.allowed:
            raise StateConflictError(decision.reason)
        if run.assigned_operator_id is None:
            raise StateConflictError("Portal run has no assigned operator.")
        browser_session = await run_service.active_browser_session(run, actor=actor)
        run.status = PortalRunStatus.ENTRY_IN_PROGRESS.value
        run.current_stage = run.status
        await PortalJobRepository(self.session).enqueue(
            job_type=PortalJobType.ENTER_FIELDS,
            idempotency_key=f"portal-enter-fields:{run.id}:{uuid.uuid4().hex}",
            portal_run_id=run.id,
            browser_session_id=browser_session.id,
            max_attempts=2,
        )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_run",
            entity_id=run.id,
            action="portal_field_entry_queued",
        )
        await self.session.commit()
        return run

    async def resolve_fields_for_worker(self, run_id: uuid.UUID) -> list[ResolvedPortalField]:
        run = await self._run(run_id)
        await PortalRunService(self.session, self.settings).revalidate_governance(run)
        rows = (
            await self.session.execute(
                select(PortalRunField, PortalFieldMapping)
                .join(
                    PortalFieldMapping,
                    PortalFieldMapping.id == PortalRunField.portal_field_mapping_id,
                )
                .where(
                    PortalRunField.portal_run_id == run.id,
                    PortalRunField.status.in_(
                        (
                            PortalFieldStatus.PENDING.value,
                            PortalFieldStatus.DISCREPANCY.value,
                        )
                    ),
                    PortalFieldMapping.human_only.is_(False),
                )
                .order_by(PortalFieldMapping.sort_order)
            )
        ).all()
        resolved: list[ResolvedPortalField] = []
        for run_field, mapping in rows:
            value, source_id = await self._resolve_value(run, mapping)
            transform = _TRANSFORMS.get(mapping.transformation_key)
            if transform is None:
                raise StateConflictError(
                    f"Unknown reviewed field transformation {mapping.transformation_key!r}."
                )
            value = transform(value)
            if mapping.allowed_values is not None:
                allowed = (
                    mapping.allowed_values
                    if isinstance(mapping.allowed_values, list)
                    else list(mapping.allowed_values)
                )
                if value not in allowed and str(value) not in {str(item) for item in allowed}:
                    raise StateConflictError(
                        f"Resolved value for {mapping.portal_field_key!r} is outside "
                        "the reviewed allowed values."
                    )
            text = str(value)
            max_length = mapping.validation_rules.get("max_length")
            if max_length is not None and len(text) > int(max_length):
                raise StateConflictError(
                    f"Resolved value for {mapping.portal_field_key!r} exceeds max length."
                )
            sensitive = mapping.sensitivity.upper() not in {"PUBLIC", "INTERNAL"}
            fingerprint = self._fingerprint(text)
            run_field.approved_source_record_id = source_id
            run_field.approved_value_fingerprint = fingerprint
            resolved.append(
                ResolvedPortalField(
                    run_field_id=run_field.id,
                    field_key=run_field.portal_field_key,
                    value=text,
                    fingerprint=fingerprint,
                    sensitive=sensitive,
                )
            )
        await self.session.flush()
        return resolved

    async def record_worker_field_result(
        self,
        run_field_id: uuid.UUID,
        *,
        entered_value: str,
        displayed_value: str,
        worker_id: str,
    ) -> PortalRunField:
        row = await self.session.get(PortalRunField, run_field_id)
        if row is None:
            raise NotFoundError("Portal run field not found.")
        mapping = (
            await self.session.get(PortalFieldMapping, row.portal_field_mapping_id)
            if row.portal_field_mapping_id
            else None
        )
        if mapping is None or mapping.human_only:
            raise StateConflictError("Human-only or unmapped fields cannot be auto-entered.")
        entered_fingerprint = self._fingerprint(entered_value)
        displayed_fingerprint = self._fingerprint(displayed_value)
        row.entered_value_fingerprint = entered_fingerprint
        row.displayed_value_redacted = redact_display(
            displayed_value, sensitive=mapping.sensitivity.upper() not in {"PUBLIC", "INTERNAL"}
        )
        row.entered_by = worker_id
        row.entered_at = utcnow()
        if (
            entered_fingerprint == row.approved_value_fingerprint
            and displayed_fingerprint == row.approved_value_fingerprint
        ):
            row.status = PortalFieldStatus.VERIFIED.value
            row.verified_by = worker_id
            row.verified_at = utcnow()
            row.discrepancy_code = None
            row.discrepancy_details = None
        else:
            row.status = PortalFieldStatus.DISCREPANCY.value
            row.discrepancy_code = "VALUE_MISMATCH"
            row.discrepancy_details = {"blocking": True}
        await self._invalidate_snapshot(row.portal_run_id, reason="Portal field changed.")
        await self.session.flush()
        return row

    async def record_human_field_observation(
        self,
        field_id: uuid.UUID,
        *,
        actor: CurrentActor,
        displayed_value: str,
        expected_approved_fingerprint: str,
        sensitive: bool,
    ) -> PortalRunField:
        row = await self.session.get(PortalRunField, field_id)
        if row is None:
            raise NotFoundError("Portal run field not found.")
        if row.approved_value_fingerprint != expected_approved_fingerprint:
            raise StateConflictError("Approved field snapshot changed before verification.")
        displayed_fingerprint = self._fingerprint(displayed_value)
        row.entered_value_fingerprint = displayed_fingerprint
        row.displayed_value_redacted = redact_display(displayed_value, sensitive=sensitive)
        row.entered_by = actor.actor_id
        row.entered_at = utcnow()
        row.verified_by = actor.actor_id
        row.verified_at = utcnow()
        if displayed_fingerprint == row.approved_value_fingerprint:
            row.status = PortalFieldStatus.VERIFIED.value
            row.discrepancy_code = None
            row.discrepancy_details = None
        else:
            row.status = PortalFieldStatus.DISCREPANCY.value
            row.discrepancy_code = "VALUE_MISMATCH"
            row.discrepancy_details = {"blocking": True}
        await self._invalidate_snapshot(row.portal_run_id, reason="Human portal field changed.")
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_run_field",
            entity_id=row.id,
            action="portal_field_human_observation",
            after={"status": row.status},
        )
        await self.session.commit()
        return row

    async def queue_document_upload(self, run_id: uuid.UUID, *, actor: CurrentActor) -> PortalRun:
        run = await self._run(run_id)
        run_service = PortalRunService(self.session, self.settings)
        portal, review = await run_service.revalidate_governance(run)
        decision = action_is_allowed(
            action="UPLOAD_DOCUMENT",
            run_level=run.automation_level,
            portal_level=portal.approved_automation_level,
            allowed_actions=review.allowed_actions,
            prohibited_actions=review.prohibited_actions,
        )
        if not decision.allowed:
            raise StateConflictError(decision.reason)
        browser_session = await run_service.active_browser_session(run, actor=actor)
        documents = list(
            await self.session.scalars(
                select(PortalRunDocument).where(PortalRunDocument.portal_run_id == run.id)
            )
        )
        if not documents:
            raise StateConflictError("Portal run has no approved packet documents.")
        if len(documents) > self.settings.portal_upload_max_files:
            raise StateConflictError("Portal document count exceeds configured upload limit.")
        total = 0
        for row in documents:
            _, version = await self._validate_document(row)
            total += version.size_bytes
            if version.mime_type not in self.settings.portal_upload_allowed_mime_types:
                raise StateConflictError("Document MIME type is not permitted for portal upload.")
            row.status = PortalDocumentStatus.UPLOAD_PENDING.value
        if total > self.settings.portal_upload_max_total_bytes:
            raise StateConflictError("Portal documents exceed configured total upload size.")
        run.status = PortalRunStatus.UPLOAD_IN_PROGRESS.value
        run.current_stage = run.status
        await PortalJobRepository(self.session).enqueue(
            job_type=PortalJobType.UPLOAD_DOCUMENTS,
            idempotency_key=f"portal-upload:{run.id}:{uuid.uuid4().hex}",
            portal_run_id=run.id,
            browser_session_id=browser_session.id,
            max_attempts=2,
        )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_run",
            entity_id=run.id,
            action="portal_document_upload_queued",
            after={"document_count": len(documents)},
        )
        await self.session.commit()
        return run

    async def record_document_observation(
        self,
        run_document_id: uuid.UUID,
        *,
        actor_id: str,
        portal_display_name: str,
        portal_size_bytes: int,
        portal_upload_reference: str | None,
    ) -> PortalRunDocument:
        row = await self.session.get(PortalRunDocument, run_document_id)
        if row is None:
            raise NotFoundError("Portal run document not found.")
        _document, version = await self._validate_document(row)
        row.portal_display_name = portal_display_name[:500]
        row.portal_size_bytes = portal_size_bytes
        row.portal_upload_reference = (
            portal_upload_reference[:500] if portal_upload_reference else None
        )
        row.uploaded_by = actor_id
        row.uploaded_at = row.uploaded_at or utcnow()
        if portal_display_name == row.expected_filename and portal_size_bytes == version.size_bytes:
            row.status = PortalDocumentStatus.VERIFIED.value
            row.verified_at = utcnow()
            row.discrepancy_details = None
        else:
            row.status = PortalDocumentStatus.FAILED_REVIEW.value
            row.discrepancy_details = {
                "code": "DOCUMENT_VERSION_MISMATCH",
                "blocking": True,
            }
        await self._invalidate_snapshot(row.portal_run_id, reason="Portal document state changed.")
        await self.session.flush()
        return row

    async def _resolve_value(
        self, run: PortalRun, mapping: PortalFieldMapping
    ) -> tuple[object, uuid.UUID | None]:
        key = mapping.source_key
        if mapping.source_type == PortalFieldSourceType.FORM_INSTANCE_FIELD.value:
            if not run.form_instance_id or not key:
                raise StateConflictError("Form field mapping has no form instance or source key.")
            result = await self.session.execute(
                select(FormFieldValue, FormTemplateField)
                .join(
                    FormTemplateField,
                    FormTemplateField.id == FormFieldValue.form_template_field_id,
                )
                .where(
                    FormFieldValue.form_instance_id == run.form_instance_id,
                    FormTemplateField.field_key == key,
                )
            )
            pair = result.first()
            if pair is None:
                raise StateConflictError(f"Approved form field {key!r} is missing.")
            row, _field = pair
            if row.status != FormFieldValueStatus.APPROVED.value:
                raise StateConflictError(f"Form field {key!r} is not approved.")
            return self._read_form_value(row), row.id
        if mapping.source_type == PortalFieldSourceType.INFORMATION_REGISTRY.value:
            if not key:
                raise StateConflictError("Information mapping has no definition key.")
            value = await self.session.scalar(
                select(InformationValue)
                .join(
                    InformationDefinition,
                    InformationDefinition.id == InformationValue.information_definition_id,
                )
                .where(
                    InformationDefinition.information_key == key,
                    InformationValue.status == "APPROVED",
                    InformationValue.legal_entity_id == run.legal_entity_id,
                )
            )
            if value is None or (value.valid_to and value.valid_to < date.today()):
                raise StateConflictError(
                    f"Information value {key!r} is missing, stale, or expired."
                )
            return self._read_information_value(value), value.id
        if mapping.source_type == PortalFieldSourceType.LEGAL_ENTITY.value:
            if key not in _ALLOWED_ENTITY_FIELDS:
                raise StateConflictError("Legal-entity source key is not allow-listed.")
            entity = await self.session.get(LegalEntity, run.legal_entity_id)
            if entity is None:
                raise NotFoundError("Legal entity not found.")
            return getattr(entity, key), entity.id
        if mapping.source_type == PortalFieldSourceType.LICENSE_INVENTORY.value:
            if key not in _ALLOWED_LICENSE_FIELDS or not run.license_id:
                raise StateConflictError(
                    "License source key is not allow-listed or no license exists."
                )
            license_record = await self.session.get(LicenseInventory, run.license_id)
            if license_record is None or license_record.legal_entity_id != run.legal_entity_id:
                raise StateConflictError("License source belongs to another legal entity.")
            return getattr(license_record, key), license_record.id
        if mapping.source_type == PortalFieldSourceType.COMPLIANCE_CASE.value:
            if key not in _ALLOWED_CASE_FIELDS:
                raise StateConflictError("Compliance-case source key is not allow-listed.")
            case = await self.session.get(ComplianceCase, run.compliance_case_id)
            if case is None or case.legal_entity_id != run.legal_entity_id:
                raise StateConflictError("Compliance case belongs to another legal entity.")
            return getattr(case, key), case.id
        raise StateConflictError(
            f"Source type {mapping.source_type!r} requires human entry or a reviewed calculator."
        )

    def _read_form_value(self, row: FormFieldValue) -> str:
        if row.value_plain is not None:
            return row.value_plain
        if not row.value_encrypted:
            raise StateConflictError("Approved form field has no value.")
        cipher = build_cipher(self.settings.information_encryption_key_reference)
        return cipher.decrypt_text(
            row.value_encrypted, entity_type="form_field_value", entity_id=str(row.id)
        )

    def _read_information_value(self, row: InformationValue) -> object:
        if row.value_plain is not None:
            return row.value_plain
        if not row.value_encrypted:
            raise StateConflictError("Approved information record has no value.")
        cipher = build_cipher(self.settings.information_encryption_key_reference)
        return cipher.decrypt_json(
            row.value_encrypted, entity_type="information_value", entity_id=str(row.id)
        )

    def _fingerprint(self, value: object) -> str:
        try:
            return build_cipher(self.settings.information_encryption_key_reference).fingerprint(
                value
            )
        except EncryptionUnavailableError:
            if self.settings.app_env not in {"local", "test"}:
                raise
            return content_sha256(value)

    async def _validate_document(self, row: PortalRunDocument) -> tuple[Document, DocumentVersion]:
        run = await self._run(row.portal_run_id)
        document = await self.session.get(Document, row.document_id)
        version = await self.session.get(DocumentVersion, row.document_version_id)
        if document is None or version is None:
            raise StateConflictError("Governed portal document is missing.")
        if (
            document.approval_status != ApprovalStatus.APPROVED.value
            or document.lifecycle_status != LifecycleStatus.ACTIVE.value
            or document.current_version_id != version.id
            or version.storage_status != StorageStatus.AVAILABLE.value
            or version.content_sha256 != row.expected_sha256
            or document.content_sha256 != row.expected_sha256
            or (document.expiry_date and document.expiry_date < date.today())
        ):
            raise StateConflictError(
                "Document is expired, unapproved, unavailable, superseded, quarantined, "
                "or hash-invalid."
            )
        # Entity isolation is inherited from the approved packet pinned to this
        # run; the packet itself was validated against the exact case.
        if not run.document_packet_id:
            raise StateConflictError("Portal upload is not bound to an approved packet.")
        return document, version

    async def _invalidate_snapshot(self, run_id: uuid.UUID, *, reason: str) -> None:
        approved = await self.session.scalar(
            select(PreSubmissionSnapshot).where(
                PreSubmissionSnapshot.portal_run_id == run_id,
                PreSubmissionSnapshot.status == SnapshotStatus.APPROVED.value,
            )
        )
        if approved:
            approved.status = SnapshotStatus.SUPERSEDED.value
            run = await self._run(run_id)
            run.status = PortalRunStatus.DISCREPANCIES_FOUND.value
            run.current_stage = run.status
            run.last_error_code = "snapshot_invalidated"
            run.last_error_message = reason[:500]

    async def _run(self, run_id: uuid.UUID) -> PortalRun:
        run = await self.session.get(PortalRun, run_id)
        if run is None:
            raise NotFoundError("Portal run not found.")
        return run

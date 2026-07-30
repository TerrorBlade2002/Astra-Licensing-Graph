"""Form template registration, prefill, review, signature tracking, and evidence.

Hard boundaries (see docs/form-preparation.md):

* Signature, initials, and attestation fields are recorded as requirements and
  never populated.
* ``record_signed_document`` accepts uploaded evidence only; it does not sign.
* ``record_external_submission`` records that a human filed elsewhere. Nothing in
  this service submits, logs into a portal, pays a fee, or attests.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.config import Settings
from app.core.crypto import EncryptionUnavailableError, build_cipher
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import (
    FORM_FIELDS_MISSING_TOTAL,
    FORM_INSTANCES_TOTAL,
    FORMS_WAITING_SIGNATURE,
)
from app.deadlines.alerts import signature_pending_alert
from app.forms.enums import (
    FILLABLE_FORMATS,
    FROZEN_INSTANCE_STATUSES,
    HUMAN_EXECUTION_FIELD_TYPES,
    OUTSTANDING_FIELD_STATUSES,
    FieldDetectionStatus,
    FieldSourceType,
    FormFieldValueStatus,
    FormFormat,
    FormInstanceStatus,
    FormTemplateStatus,
    FormValidationCode,
    MappingStatus,
    SignatureRequirementStatus,
)
from app.forms.filling import FieldValue, fill_template, verify_signed_document
from app.forms.inspection import InspectionResult, inspect_template
from app.forms.mappings import (
    MappingSpec,
    apply_transformation,
    classify_unmapped,
    mask_for_display,
    validate_against_allowed,
)
from app.forms.worksheets import (
    WorksheetContext,
    WorksheetRow,
    render_csv_worksheet,
    render_text_worksheet,
)
from app.information_registry.enums import UsagePurpose
from app.information_registry.scoping import UsageContext, requires_encryption
from app.licensing.audit import add_licensing_audit, record_notification
from app.models import (
    ComplianceCase,
    Document,
    DocumentVersion,
    FormFieldMapping,
    FormFieldValue,
    FormInstance,
    FormTemplate,
    FormTemplateField,
    Jurisdiction,
    LegalEntity,
    LicenseInventory,
)
from app.models.mixins import utcnow
from app.services.information_registry_service import InformationRegistryService

_ENTITY_TYPE = "form_field_value"


class FormPreparationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.registry = InformationRegistryService(session, settings)

    # ------------------------------------------------------------------ templates
    async def register_template(
        self, *, actor: CurrentActor, commit: bool = True, **fields: Any
    ) -> FormTemplate:
        template_key = fields["template_key"]
        existing = await self.session.scalar(
            select(FormTemplate).where(FormTemplate.template_key == template_key)
        )
        if existing:
            raise StateConflictError(f"Template key {template_key!r} already exists.")
        document = await self.session.get(Document, fields["template_document_id"])
        if document is None:
            raise NotFoundError("The governed template document was not found.")
        version = (
            await self.session.get(DocumentVersion, document.current_version_id)
            if document.current_version_id
            else None
        )
        if (
            document.lifecycle_status != "ACTIVE"
            or document.approval_status != "APPROVED"
            or version is None
            or version.storage_status != "AVAILABLE"
        ):
            raise StateConflictError(
                "A form template must reference an approved, active, available "
                "governed document version."
            )
        supplied_hash = fields.get("template_sha256")
        if supplied_hash and supplied_hash.lower() != version.content_sha256.lower():
            raise StateConflictError(
                "The supplied template hash does not match the governed document version."
            )
        template = FormTemplate(
            template_key=template_key,
            name=fields["name"],
            form_family=fields["form_family"],
            jurisdiction_id=fields.get("jurisdiction_id"),
            license_type_id=fields.get("license_type_id"),
            version=int(fields.get("version") or 1),
            template_document_id=fields["template_document_id"],
            form_format=fields.get("form_format") or FormFormat.UNKNOWN.value,
            field_detection_status=FieldDetectionStatus.NOT_INSPECTED.value,
            status=FormTemplateStatus.DRAFT.value,
            effective_from=fields.get("effective_from"),
            effective_to=fields.get("effective_to"),
            template_sha256=version.content_sha256.lower(),
        )
        self.session.add(template)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="form_template",
            entity_id=template.id,
            action="form_template_registered",
            after={"template_key": template_key, "format": template.form_format},
        )
        if commit:
            await self.session.commit()
        return template

    async def inspect(
        self,
        template_id: uuid.UUID,
        *,
        actor: CurrentActor,
        content: bytes,
        filename: str,
        commit: bool = True,
    ) -> InspectionResult:
        """Inspect a template and persist the detected fields."""
        template = await self.session.get(FormTemplate, template_id)
        if template is None:
            raise NotFoundError("Form template not found.")
        if len(content) > self.settings.form_max_template_bytes:
            raise StateConflictError("The template exceeds FORM_MAX_TEMPLATE_BYTES.")
        self._verify_template_content(template, content)

        result = inspect_template(content, filename=filename, declared_format=template.form_format)
        template.form_format = result.form_format
        template.field_detection_status = result.detection_status
        template.detected_field_count = result.field_count
        template.inspection_notes = "\n".join(result.notes)[:4000]
        template.status = FormTemplateStatus.PENDING_REVIEW.value

        existing = {
            field.field_key: field
            for field in await self.session.scalars(
                select(FormTemplateField).where(FormTemplateField.form_template_id == template.id)
            )
        }
        for detected in result.fields:
            row = existing.get(detected.field_key)
            if row is None:
                self.session.add(
                    FormTemplateField(
                        form_template_id=template.id,
                        field_key=detected.field_key,
                        native_field_name=detected.native_field_name,
                        label=detected.label,
                        field_type=detected.field_type,
                        required=detected.required,
                        allowed_values=detected.allowed_values,
                        page_number=detected.page_number,
                        instructions=detected.instructions,
                        sensitivity=detected.sensitivity,
                        max_length=detected.max_length,
                        sort_order=detected.sort_order,
                    )
                )
            else:
                row.native_field_name = detected.native_field_name
                row.label = detected.label
                row.field_type = detected.field_type
                row.required = detected.required
                row.allowed_values = detected.allowed_values
                row.page_number = detected.page_number
                row.sort_order = detected.sort_order
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="form_template",
            entity_id=template.id,
            action="form_template_inspected",
            after={"fields": result.field_count, "format": result.form_format},
        )
        if commit:
            await self.session.commit()
        return result

    async def activate_template(
        self,
        template_id: uuid.UUID,
        *,
        actor: CurrentActor,
        commit: bool = True,
    ) -> FormTemplate:
        """Approve an inspected, hash-pinned template for new form instances."""
        template = await self.session.get(FormTemplate, template_id)
        if template is None:
            raise NotFoundError("Form template not found.")
        if template.status == FormTemplateStatus.RETIRED.value:
            raise StateConflictError("A retired template cannot be reactivated.")
        if template.field_detection_status in (
            FieldDetectionStatus.NOT_INSPECTED.value,
            FieldDetectionStatus.INSPECTION_FAILED.value,
        ):
            raise StateConflictError("Inspect the governed template before activating it.")
        if not template.template_sha256:
            raise StateConflictError("The template has no immutable content hash.")
        template.status = FormTemplateStatus.ACTIVE.value
        template.reviewed_by_actor = actor.actor_id
        template.reviewed_at = utcnow()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="form_template",
            entity_id=template.id,
            action="form_template_activated",
            after={
                "template_sha256": template.template_sha256,
                "version": template.version,
            },
        )
        if commit:
            await self.session.commit()
        return template

    async def upsert_mapping(
        self,
        field_id: uuid.UUID,
        *,
        actor: CurrentActor,
        source_type: str,
        source_key: str | None = None,
        transformation: str | None = None,
        approve: bool = False,
        commit: bool = True,
    ) -> FormFieldMapping:
        """Propose or approve a field mapping. Approval is what enables autofill."""
        field = await self.session.get(FormTemplateField, field_id)
        if field is None:
            raise NotFoundError("Template field not found.")
        if field.field_type in HUMAN_EXECUTION_FIELD_TYPES and source_type != (
            FieldSourceType.SIGNATURE_REQUIRED.value
        ):
            raise StateConflictError(
                "A signature, initials, or attestation field can only be mapped to "
                "SIGNATURE_REQUIRED; it is never populated from data."
            )
        mapping = await self.session.scalar(
            select(FormFieldMapping).where(
                FormFieldMapping.form_template_field_id == field_id,
                FormFieldMapping.mapping_status.in_(
                    (MappingStatus.PROPOSED.value, MappingStatus.APPROVED.value)
                ),
            )
        )
        if mapping is None:
            mapping = FormFieldMapping(
                form_template_field_id=field_id,
                source_type=source_type,
                source_key=source_key,
                transformation=transformation,
                mapping_status=MappingStatus.PROPOSED.value,
                requires_review=True,
            )
            self.session.add(mapping)
        else:
            mapping.source_type = source_type
            mapping.source_key = source_key
            mapping.transformation = transformation
        if approve:
            mapping.mapping_status = MappingStatus.APPROVED.value
            mapping.requires_review = False
            mapping.approved_by_actor = actor.actor_id
            mapping.approved_at = utcnow()
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="form_field_mapping",
            entity_id=mapping.id,
            action="form_field_mapping_saved",
            after={"status": mapping.mapping_status, "source_type": source_type},
        )
        if commit:
            await self.session.commit()
        return mapping

    # ------------------------------------------------------------------ instances
    async def create_instance(
        self,
        case_id: uuid.UUID,
        *,
        actor: CurrentActor,
        form_template_id: uuid.UUID,
        commit: bool = True,
    ) -> FormInstance:
        case = await self.session.get(ComplianceCase, case_id)
        template = await self.session.get(FormTemplate, form_template_id)
        if case is None or template is None:
            raise NotFoundError("Case or form template not found.")
        if not self.settings.form_preparation_enabled:
            raise StateConflictError("Form preparation is disabled by configuration.")
        if template.status != FormTemplateStatus.ACTIVE.value:
            raise StateConflictError(
                "Only a reviewed, active form template can create a form instance."
            )
        highest = (
            await self.session.scalar(
                select(func.max(FormInstance.version)).where(
                    FormInstance.compliance_case_id == case_id,
                    FormInstance.form_template_id == form_template_id,
                )
            )
            or 0
        )
        instance = FormInstance(
            instance_key=f"{case.case_key}-{template.template_key}-{highest + 1}",
            compliance_case_id=case_id,
            form_template_id=form_template_id,
            version=highest + 1,
            status=FormInstanceStatus.DRAFT.value,
            prepared_by_actor=actor.actor_id,
            signature_status=SignatureRequirementStatus.NOT_REQUIRED.value,
        )
        self.session.add(instance)
        await self.session.flush()
        FORM_INSTANCES_TOTAL.inc()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="form_instance",
            entity_id=instance.id,
            action="form_instance_created",
            after={"version": instance.version},
        )
        if commit:
            await self.session.commit()
        return instance

    async def prefill(
        self, instance_id: uuid.UUID, *, actor: CurrentActor, commit: bool = True
    ) -> FormInstance:
        """Resolve approved values into field values; flag what is missing."""
        instance = await self.session.get(FormInstance, instance_id)
        if instance is None:
            raise NotFoundError("Form instance not found.")
        if instance.status in FROZEN_INSTANCE_STATUSES:
            raise StateConflictError(
                f"A {instance.status} instance is frozen. Create a new version to change it."
            )
        case = await self.session.get(ComplianceCase, instance.compliance_case_id)
        template = await self.session.get(FormTemplate, instance.form_template_id)
        if case is None or template is None:
            raise NotFoundError("Case or template not found.")
        entity = await self.session.get(LegalEntity, case.legal_entity_id)
        licence = (
            await self.session.get(LicenseInventory, case.license_id) if case.license_id else None
        )

        fields = list(
            await self.session.scalars(
                select(FormTemplateField)
                .where(FormTemplateField.form_template_id == template.id)
                .order_by(FormTemplateField.sort_order)
            )
        )
        mappings = {
            m.form_template_field_id: m
            for m in await self.session.scalars(
                select(FormFieldMapping).where(
                    FormFieldMapping.form_template_field_id.in_([f.id for f in fields]),
                    FormFieldMapping.mapping_status == MappingStatus.APPROVED.value,
                )
            )
        }

        for existing in list(
            await self.session.scalars(
                select(FormFieldValue).where(FormFieldValue.form_instance_id == instance.id)
            )
        ):
            await self.session.delete(existing)
        await self.session.flush()

        context = UsageContext(
            legal_entity_id=case.legal_entity_id,
            jurisdiction_id=licence.jurisdiction_id if licence else None,
            license_id=case.license_id,
            vendor_organization_id=case.vendor_organization_id,
            compliance_case_id=case.id,
        )
        cipher = None
        try:
            cipher = build_cipher(self.settings.information_encryption_key_reference)
        except EncryptionUnavailableError:
            cipher = None

        missing: list[dict[str, Any]] = []
        validations: list[dict[str, Any]] = []
        signature_required = False
        missing_count = 0

        for field in fields:
            mapping = mappings.get(field.id)
            spec = (
                MappingSpec(
                    form_template_field_id=field.id,
                    field_key=field.field_key,
                    source_type=mapping.source_type,
                    source_key=mapping.source_key,
                    transformation=mapping.transformation,
                    mapping_status=mapping.mapping_status,
                    requires_review=mapping.requires_review,
                    default_value=mapping.default_value,
                )
                if mapping
                else None
            )

            if field.field_type in HUMAN_EXECUTION_FIELD_TYPES:
                signature_required = True
                self._add_field_value(
                    instance_id=instance.id,
                    field=field,
                    status=FormFieldValueStatus.SIGNATURE_REQUIRED.value,
                    source_type=FieldSourceType.SIGNATURE_REQUIRED.value,
                    value=None,
                    cipher=cipher,
                    unresolved_reason="Requires personal execution by an authorised signatory.",
                )
                continue

            if spec is None or not spec.is_usable:
                resolved = classify_unmapped(
                    field_key=field.field_key,
                    form_template_field_id=field.id,
                    native_field_name=field.native_field_name,
                    field_type=field.field_type,
                    label=field.label,
                    required=field.required,
                    sensitivity=field.sensitivity,
                    page_number=field.page_number,
                    instructions=field.instructions,
                    sort_order=field.sort_order,
                )
                self._add_field_value(
                    instance_id=instance.id,
                    field=field,
                    status=resolved.status,
                    source_type=resolved.source_type,
                    value=None,
                    cipher=cipher,
                    unresolved_reason=resolved.unresolved_reason,
                )
                if resolved.validation_code:
                    validations.append(
                        {"field_key": field.field_key, "code": resolved.validation_code}
                    )
                if field.required:
                    missing.append(
                        {
                            "field_key": field.field_key,
                            "label": field.label,
                            "reason": resolved.unresolved_reason,
                        }
                    )
                    missing_count += 1
                continue

            raw: Any = None
            source_record_id: uuid.UUID | None = None
            source_version: int | None = None
            unresolved: str | None = None

            if spec.source_type == FieldSourceType.INFORMATION_REGISTRY.value and spec.source_key:
                lookup = await self.registry.resolve_for_use(
                    information_key=spec.source_key, context=context
                )
                if lookup["found"]:
                    record = lookup["record"]
                    source_record_id = record.id
                    source_version = record.value_version
                    raw = await self._read_value(record, cipher)
                    await self.registry.record_usage(
                        record.id,
                        purpose=UsagePurpose.FORM_PREFILL.value,
                        actor=actor,
                        compliance_case_id=case.id,
                        form_instance_id=instance.id,
                        commit=False,
                    )
                else:
                    reason = lookup.get("reason") or "NO_APPROVED_VALUE"
                    unresolved = f"No usable approved value ({reason})."
                    code = {
                        "STALE": FormValidationCode.STALE_INFORMATION_VALUE.value,
                        "EXPIRED": FormValidationCode.EXPIRED_INFORMATION_VALUE.value,
                        "NOT_APPROVED": FormValidationCode.UNAPPROVED_INFORMATION_VALUE.value,
                        "WRONG_ENTITY": FormValidationCode.WRONG_ENTITY_INFORMATION_VALUE.value,
                    }.get(reason)
                    if code:
                        validations.append({"field_key": field.field_key, "code": code})
            elif spec.source_type == FieldSourceType.LEGAL_ENTITY.value and entity is not None:
                raw = getattr(entity, spec.source_key or "", None)
                source_record_id = entity.id
            elif (
                spec.source_type == FieldSourceType.LICENSE_INVENTORY.value and licence is not None
            ):
                raw = getattr(licence, spec.source_key or "", None)
                source_record_id = licence.id
            elif spec.source_type == FieldSourceType.COMPLIANCE_CASE.value:
                raw = getattr(case, spec.source_key or "", None)
                source_record_id = case.id
            elif spec.source_type == FieldSourceType.CALCULATED.value:
                raw = {"today": utcnow().date().isoformat()}.get(spec.source_key or "")
            elif spec.source_type == FieldSourceType.MANUAL_INPUT.value:
                raw = spec.default_value

            if raw is None or raw == "":
                self._add_field_value(
                    instance_id=instance.id,
                    field=field,
                    status=FormFieldValueStatus.NEEDS_INFORMATION.value,
                    source_type=spec.source_type,
                    value=None,
                    cipher=cipher,
                    unresolved_reason=unresolved or "No value is available for this field.",
                    source_record_id=source_record_id,
                )
                if field.required:
                    missing.append(
                        {
                            "field_key": field.field_key,
                            "label": field.label,
                            "information_key": spec.source_key,
                            "reason": unresolved or "No value available.",
                        }
                    )
                    missing_count += 1
                continue

            text = apply_transformation(raw, spec.transformation)
            if not validate_against_allowed(text, field.allowed_values):
                validations.append(
                    {
                        "field_key": field.field_key,
                        "code": FormValidationCode.VALUE_NOT_IN_ALLOWED_SET.value,
                    }
                )
                self._add_field_value(
                    instance_id=instance.id,
                    field=field,
                    status=FormFieldValueStatus.NEEDS_REVIEW.value,
                    source_type=spec.source_type,
                    value=text,
                    cipher=cipher,
                    unresolved_reason="The resolved value is not an allowed option.",
                    source_record_id=source_record_id,
                    source_version=source_version,
                )
                continue

            self._add_field_value(
                instance_id=instance.id,
                field=field,
                status=FormFieldValueStatus.AUTO_FILLED.value,
                source_type=spec.source_type,
                value=text,
                cipher=cipher,
                source_record_id=source_record_id,
                source_version=source_version,
            )

        await self.session.flush()
        outstanding_rows = list(
            await self.session.scalars(
                select(FormFieldValue).where(
                    FormFieldValue.form_instance_id == instance.id,
                    FormFieldValue.status.in_(OUTSTANDING_FIELD_STATUSES),
                )
            )
        )
        fields_by_id = {field.id: field for field in fields}
        known_missing = {item["field_key"] for item in missing}
        for row in outstanding_rows:
            outstanding_field = fields_by_id.get(row.form_template_field_id)
            if outstanding_field and outstanding_field.field_key not in known_missing:
                missing.append(
                    {
                        "field_key": outstanding_field.field_key,
                        "label": outstanding_field.label,
                        "reason": row.unresolved_reason
                        or "This field requires reviewed information.",
                    }
                )
                known_missing.add(field.field_key)
                missing_count += 1

        instance.missing_fields = missing
        instance.validation_results = validations
        instance.signature_required = signature_required
        instance.signature_status = (
            SignatureRequirementStatus.IDENTIFIED.value
            if signature_required
            else SignatureRequirementStatus.NOT_REQUIRED.value
        )
        instance.status = (
            FormInstanceStatus.MISSING_INFORMATION.value
            if missing
            else FormInstanceStatus.PREFILLED.value
        )
        if missing_count:
            FORM_FIELDS_MISSING_TOTAL.inc(missing_count)
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="form_instance",
            entity_id=instance.id,
            action="form_instance_prefilled",
            after={
                "status": instance.status,
                "missing": len(missing),
                "signature_required": signature_required,
            },
        )
        if commit:
            await self.session.commit()
        return instance

    def _add_field_value(
        self,
        *,
        instance_id: uuid.UUID,
        field: FormTemplateField,
        status: str,
        source_type: str,
        value: str | None,
        cipher: Any,
        unresolved_reason: str | None = None,
        source_record_id: uuid.UUID | None = None,
        source_version: int | None = None,
    ) -> FormFieldValue:
        row = FormFieldValue(
            id=uuid.uuid4(),
            form_instance_id=instance_id,
            form_template_field_id=field.id,
            source_type=source_type,
            source_record_id=source_record_id,
            source_value_version=source_version,
            status=status,
            unresolved_reason=unresolved_reason,
        )
        if value is not None:
            if requires_encryption(field.sensitivity):
                if cipher is None:
                    row.status = FormFieldValueStatus.NEEDS_INFORMATION.value
                    row.unresolved_reason = (
                        "Sensitive value could not be protected because encryption "
                        "key material is unavailable."
                    )
                else:
                    row.value_encrypted = cipher.encrypt(
                        value, entity_type=_ENTITY_TYPE, entity_id=str(row.id)
                    )
            else:
                row.value_plain = value[:4000]
            if row.status != FormFieldValueStatus.NEEDS_INFORMATION.value:
                row.display_value_redacted = mask_for_display(value, field.sensitivity)
        self.session.add(row)
        return row

    async def _read_value(self, record: Any, cipher: Any) -> Any:
        """Read a registry value for filling, decrypting only when necessary."""
        if record.value_plain and isinstance(record.value_plain, dict):
            return record.value_plain.get("value")
        if record.value_encrypted and cipher is not None:
            payload = cipher.decrypt_json(
                record.value_encrypted,
                entity_type="information_value",
                entity_id=str(record.id),
            )
            return payload.get("value") if isinstance(payload, dict) else payload
        return None

    async def set_field(
        self,
        instance_id: uuid.UUID,
        *,
        actor: CurrentActor,
        field_key: str,
        value: str | None,
        status: str | None = None,
        commit: bool = True,
    ) -> FormFieldValue:
        """Manually set or review one field value."""
        instance = await self.session.get(FormInstance, instance_id)
        if instance is None:
            raise NotFoundError("Form instance not found.")
        if instance.status in FROZEN_INSTANCE_STATUSES:
            raise StateConflictError(f"A {instance.status} instance is frozen.")
        field = await self.session.scalar(
            select(FormTemplateField).where(
                FormTemplateField.form_template_id == instance.form_template_id,
                FormTemplateField.field_key == field_key,
            )
        )
        if field is None:
            raise NotFoundError(f"Field {field_key!r} is not on this template.")
        if field.field_type in HUMAN_EXECUTION_FIELD_TYPES and value:
            raise StateConflictError(
                "A signature, initials, or attestation field cannot be filled with a "
                "value. It must be executed by an authorised person."
            )
        row = await self.session.scalar(
            select(FormFieldValue).where(
                FormFieldValue.form_instance_id == instance_id,
                FormFieldValue.form_template_field_id == field.id,
            )
        )
        if row is None:
            raise NotFoundError("Field value not found; prefill the instance first.")
        if value is not None and not validate_against_allowed(value, field.allowed_values):
            raise StateConflictError("The value is not one of the allowed options.")

        cipher = None
        try:
            cipher = build_cipher(self.settings.information_encryption_key_reference)
        except EncryptionUnavailableError:
            cipher = None
        if value is not None:
            if requires_encryption(field.sensitivity) and cipher is None:
                raise StateConflictError(
                    "Sensitive field values cannot be stored because encryption "
                    "key material is unavailable."
                )
            if requires_encryption(field.sensitivity):
                assert cipher is not None
                row.value_encrypted = cipher.encrypt(
                    value, entity_type=_ENTITY_TYPE, entity_id=str(row.id)
                )
                row.value_plain = None
            else:
                row.value_plain = value[:4000]
            row.display_value_redacted = mask_for_display(value, field.sensitivity)
            row.unresolved_reason = None
        row.status = status or FormFieldValueStatus.MANUALLY_FILLED.value
        row.source_type = FieldSourceType.MANUAL_INPUT.value
        row.reviewed_by_actor = actor.actor_id
        row.reviewed_at = utcnow()

        outstanding = list(
            await self.session.scalars(
                select(FormFieldValue.status).where(
                    FormFieldValue.form_instance_id == instance_id,
                    FormFieldValue.status.in_(OUTSTANDING_FIELD_STATUSES),
                )
            )
        )
        instance.missing_fields = [
            m for m in (instance.missing_fields or []) if m.get("field_key") != field_key
        ]
        if not outstanding and instance.status == FormInstanceStatus.MISSING_INFORMATION.value:
            instance.status = FormInstanceStatus.PREFILLED.value
        if commit:
            await self.session.commit()
        return row

    async def generate_draft(
        self,
        instance_id: uuid.UUID,
        *,
        actor: CurrentActor,
        template_content: bytes,
        flatten: bool = False,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Render a draft document from the current field values."""
        instance = await self.session.get(FormInstance, instance_id)
        if instance is None:
            raise NotFoundError("Form instance not found.")
        template = await self.session.get(FormTemplate, instance.form_template_id)
        if template is None:
            raise NotFoundError("Form template not found.")
        self._verify_template_content(template, template_content)
        if template.form_format not in FILLABLE_FORMATS:
            raise StateConflictError(
                f"{template.form_format} cannot be filled mechanically. Generate a "
                "field worksheet instead."
            )
        if template.form_format == FormFormat.PDF_ACROFORM.value and not (
            self.settings.form_pdf_filling_enabled
        ):
            raise StateConflictError("PDF filling is disabled by configuration.")
        if template.form_format == FormFormat.DOCX.value and not (
            self.settings.form_docx_filling_enabled
        ):
            raise StateConflictError("DOCX filling is disabled by configuration.")

        unresolved_count = (
            await self.session.scalar(
                select(func.count())
                .select_from(FormFieldValue)
                .where(
                    FormFieldValue.form_instance_id == instance.id,
                    FormFieldValue.status.in_(OUTSTANDING_FIELD_STATUSES),
                )
            )
            or 0
        )
        if unresolved_count:
            raise StateConflictError(
                "Resolve every missing or review-required field before generating a form draft.",
                details={"outstanding_fields": int(unresolved_count)},
            )
        values = await self._field_values_for_fill(instance)
        result = fill_template(
            template_content,
            values,
            form_format=template.form_format,
            flatten=flatten,
            allow_flatten=self.settings.form_flatten_after_approval_enabled
            and instance.status == FormInstanceStatus.APPROVED_FOR_SIGNATURE.value,
        )
        instance.field_snapshot_sha256 = result.field_snapshot_sha256
        instance.generated_size_bytes = len(result.content)
        outstanding = list(
            await self.session.scalars(
                select(FormFieldValue.status).where(
                    FormFieldValue.form_instance_id == instance.id,
                    FormFieldValue.status.in_(OUTSTANDING_FIELD_STATUSES),
                )
            )
        )
        if not outstanding and instance.status in (
            FormInstanceStatus.PREFILLED.value,
            FormInstanceStatus.DRAFT.value,
        ):
            instance.status = FormInstanceStatus.READY_FOR_REVIEW.value
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="form_instance",
            entity_id=instance.id,
            action="form_draft_generated",
            after={
                "filled_fields": len(result.filled_fields),
                "signature_fields_skipped": len(result.skipped_signature_fields),
                "draft_sha256": result.content_sha256,
            },
        )
        if commit:
            await self.session.commit()
        return {
            "content": result.content,
            "content_sha256": result.content_sha256,
            "field_snapshot_sha256": result.field_snapshot_sha256,
            "filled_fields": result.filled_fields,
            "skipped_signature_fields": result.skipped_signature_fields,
            "unmatched_fields": result.unmatched_fields,
            "notes": result.notes,
        }

    @staticmethod
    def _verify_template_content(template: FormTemplate, content: bytes) -> None:
        """Reject Outlook/browser-side substitutions for a governed template."""
        actual = hashlib.sha256(content).hexdigest()
        expected = (template.template_sha256 or "").lower()
        if not expected or actual != expected:
            raise StateConflictError(
                "Uploaded template bytes do not match the approved governed template snapshot."
            )

    async def _field_values_for_fill(self, instance: FormInstance) -> list[FieldValue]:
        rows = (
            await self.session.execute(
                select(FormFieldValue, FormTemplateField)
                .join(
                    FormTemplateField,
                    FormTemplateField.id == FormFieldValue.form_template_field_id,
                )
                .where(FormFieldValue.form_instance_id == instance.id)
                .order_by(FormTemplateField.sort_order)
            )
        ).all()
        cipher = None
        try:
            cipher = build_cipher(self.settings.information_encryption_key_reference)
        except EncryptionUnavailableError:
            cipher = None

        values: list[FieldValue] = []
        for row, field in rows:
            text: str | None = row.value_plain
            if text is None and row.value_encrypted and cipher is not None:
                try:
                    text = cipher.decrypt_text(
                        row.value_encrypted, entity_type=_ENTITY_TYPE, entity_id=str(row.id)
                    )
                except Exception:
                    text = None
            values.append(
                FieldValue(
                    field_key=field.field_key,
                    native_field_name=field.native_field_name,
                    field_type=field.field_type,
                    value=text,
                    human_execution_required=row.status
                    == FormFieldValueStatus.SIGNATURE_REQUIRED.value,
                )
            )
        return values

    async def worksheet(self, instance_id: uuid.UUID, *, fmt: str = "text") -> tuple[str, str]:
        """Render a field worksheet. Returns ``(content, media_type)``."""
        instance = await self.session.get(FormInstance, instance_id)
        if instance is None:
            raise NotFoundError("Form instance not found.")
        if not self.settings.form_flat_pdf_worksheet_enabled:
            raise StateConflictError("Worksheet generation is disabled by configuration.")
        template = await self.session.get(FormTemplate, instance.form_template_id)
        case = await self.session.get(ComplianceCase, instance.compliance_case_id)
        entity = await self.session.get(LegalEntity, case.legal_entity_id) if case else None
        licence = (
            await self.session.get(LicenseInventory, case.license_id)
            if case and case.license_id
            else None
        )
        jurisdiction = (
            await self.session.get(Jurisdiction, licence.jurisdiction_id) if licence else None
        )
        rows = (
            await self.session.execute(
                select(FormFieldValue, FormTemplateField)
                .join(
                    FormTemplateField,
                    FormTemplateField.id == FormFieldValue.form_template_field_id,
                )
                .where(FormFieldValue.form_instance_id == instance.id)
                .order_by(FormTemplateField.sort_order)
            )
        ).all()
        worksheet_rows = [
            WorksheetRow(
                sort_order=field.sort_order,
                field_key=field.field_key,
                label=field.label,
                field_type=field.field_type,
                required=field.required,
                status=row.status,
                display_value=row.display_value_redacted,
                source=row.source_type,
                sensitivity=field.sensitivity,
                page_number=field.page_number,
                instructions=field.instructions or row.unresolved_reason,
            )
            for row, field in rows
        ]
        context = WorksheetContext(
            form_name=template.name if template else "Form",
            template_key=template.template_key if template else "unknown",
            template_version=template.version if template else 1,
            case_key=case.case_key if case else "unknown",
            legal_entity_name=entity.legal_name if entity else "unknown",
            jurisdiction_name=jurisdiction.name if jurisdiction else None,
            prepared_by_actor=instance.prepared_by_actor,
            form_format=template.form_format if template else None,
        )
        if fmt == "csv":
            return render_csv_worksheet(context, worksheet_rows), "text/csv"
        return render_text_worksheet(context, worksheet_rows), "text/plain"

    async def approve_for_signature(
        self,
        instance_id: uuid.UUID,
        *,
        actor: CurrentActor,
        approved_draft_sha256: str,
        required_signatory_actor: str | None = None,
        required_signatory_title: str | None = None,
        commit: bool = True,
    ) -> FormInstance:
        """Mark a reviewed draft ready for a human signature."""
        instance = await self.session.get(FormInstance, instance_id)
        if instance is None:
            raise NotFoundError("Form instance not found.")
        if instance.status not in (
            FormInstanceStatus.READY_FOR_REVIEW.value,
            FormInstanceStatus.PREFILLED.value,
        ):
            raise StateConflictError(
                f"An instance in {instance.status} cannot be approved for signature."
            )
        outstanding = list(
            await self.session.scalars(
                select(FormFieldValue.status).where(
                    FormFieldValue.form_instance_id == instance.id,
                    FormFieldValue.status.in_(OUTSTANDING_FIELD_STATUSES),
                )
            )
        )
        if outstanding:
            raise StateConflictError(
                "Every field must be resolved or reviewed before signature approval.",
                details={"outstanding_fields": len(outstanding)},
            )
        generated = (
            await self.session.get(Document, instance.generated_document_id)
            if instance.generated_document_id
            else None
        )
        generated_version = (
            await self.session.get(DocumentVersion, generated.current_version_id)
            if generated and generated.current_version_id
            else None
        )
        if (
            generated is None
            or generated_version is None
            or generated.lifecycle_status != "ACTIVE"
            or generated.approval_status != "APPROVED"
            or generated_version.storage_status != "AVAILABLE"
        ):
            raise StateConflictError(
                "The exact generated draft must be approved and available in "
                "governed storage before signature approval."
            )
        expected_draft_hash = generated_version.content_sha256.lower()
        if (
            approved_draft_sha256.lower() != expected_draft_hash
            or generated.content_sha256.lower() != expected_draft_hash
        ):
            raise StateConflictError(
                "The approved draft hash does not match the generated governed document version."
            )
        instance.approved_draft_sha256 = approved_draft_sha256
        instance.reviewed_by_actor = actor.actor_id
        instance.reviewed_at = utcnow()
        instance.required_signatory_actor = required_signatory_actor
        instance.required_signatory_title = required_signatory_title
        if instance.signature_required:
            instance.status = FormInstanceStatus.SIGNATURE_PENDING.value
            instance.signature_status = SignatureRequirementStatus.APPROVED_FOR_SIGNATURE.value
            case = await self.session.get(ComplianceCase, instance.compliance_case_id)
            recipient = required_signatory_actor or (case.assigned_owner if case else None)
            if recipient and case:
                await record_notification(
                    self.session,
                    signature_pending_alert(
                        form_instance_id=instance.id,
                        compliance_case_id=case.id,
                        recipient_actor=recipient,
                    ),
                )
        else:
            instance.status = FormInstanceStatus.READY_FOR_SUBMISSION.value
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="form_instance",
            entity_id=instance.id,
            action="form_approved_for_signature",
            after={"status": instance.status, "signature_required": instance.signature_required},
        )
        if commit:
            await self.session.commit()
        await self.refresh_metrics()
        return instance

    async def record_signed_document(
        self,
        instance_id: uuid.UUID,
        *,
        actor: CurrentActor,
        signed_document_id: uuid.UUID,
        signed_content_sha256: str,
        signed_page_count: int | None = None,
        commit: bool = True,
    ) -> FormInstance:
        """Record externally-obtained signature evidence.

        This never produces a signature. It records that one was obtained and
        checks the upload is not simply the unsigned draft.
        """
        instance = await self.session.get(FormInstance, instance_id)
        if instance is None:
            raise NotFoundError("Form instance not found.")
        if self.settings.form_signature_automation_enabled:
            raise StateConflictError("Signature automation must remain disabled.")
        if instance.status not in (
            FormInstanceStatus.SIGNATURE_PENDING.value,
            FormInstanceStatus.APPROVED_FOR_SIGNATURE.value,
        ):
            raise StateConflictError(
                f"An instance in {instance.status} is not awaiting a signature."
            )
        signed = await self.session.get(Document, signed_document_id)
        signed_version = (
            await self.session.get(DocumentVersion, signed.current_version_id)
            if signed and signed.current_version_id
            else None
        )
        case = await self.session.get(ComplianceCase, instance.compliance_case_id)
        entity = await self.session.get(LegalEntity, case.legal_entity_id) if case else None
        if (
            signed is None
            or signed_version is None
            or signed.lifecycle_status != "ACTIVE"
            or signed.approval_status != "APPROVED"
            or signed_version.storage_status != "AVAILABLE"
        ):
            raise StateConflictError(
                "Signed evidence must be an approved, active, available governed document."
            )
        expected_signed_hash = signed_version.content_sha256.lower()
        if (
            signed_content_sha256.lower() != expected_signed_hash
            or signed.content_sha256.lower() != expected_signed_hash
        ):
            raise StateConflictError(
                "The signed-content hash does not match the governed document version."
            )
        if entity and signed.legal_entity not in (entity.entity_key, entity.legal_name):
            raise StateConflictError("The signed document belongs to a different legal entity.")
        ok, message = verify_signed_document(
            approved_draft_sha256=instance.approved_draft_sha256,
            signed_content_sha256=signed_content_sha256,
            signed_page_count=signed_page_count,
        )
        if not ok:
            raise StateConflictError(message)

        instance.signed_document_id = signed_document_id
        instance.signed_recorded_by_actor = actor.actor_id
        instance.signed_recorded_at = utcnow()
        instance.status = FormInstanceStatus.SIGNED.value
        instance.signature_status = SignatureRequirementStatus.SIGNED_EVIDENCE_RECORDED.value
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="form_instance",
            entity_id=instance.id,
            action="form_signed_document_recorded",
            after={"status": instance.status, "verification": message},
        )
        if commit:
            await self.session.commit()
        await self.refresh_metrics()
        return instance

    async def record_external_submission(
        self,
        instance_id: uuid.UUID,
        *,
        actor: CurrentActor,
        reference: str,
        commit: bool = True,
    ) -> FormInstance:
        """Record that a human submitted the filing outside this system."""
        instance = await self.session.get(FormInstance, instance_id)
        if instance is None:
            raise NotFoundError("Form instance not found.")
        if instance.signature_required and instance.signed_document_id is None:
            raise StateConflictError(
                "This form requires a signature. Record the signed document first."
            )
        if instance.status not in (
            FormInstanceStatus.SIGNED.value,
            FormInstanceStatus.READY_FOR_SUBMISSION.value,
        ):
            raise StateConflictError(
                f"An instance in {instance.status} cannot be recorded as submitted."
            )
        instance.status = FormInstanceStatus.SUBMITTED_EXTERNALLY.value
        instance.external_submission_reference = reference[:300]
        instance.external_submission_recorded_by_actor = actor.actor_id
        instance.external_submission_recorded_at = utcnow()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="form_instance",
            entity_id=instance.id,
            action="form_external_submission_recorded",
            after={"status": instance.status},
            metadata={"note": "Recorded human action; no automated submission occurred."},
        )
        if commit:
            await self.session.commit()
        return instance

    async def detail(self, instance_id: uuid.UUID) -> dict[str, Any]:
        instance = await self.session.get(FormInstance, instance_id)
        if instance is None:
            raise NotFoundError("Form instance not found.")
        rows = (
            await self.session.execute(
                select(FormFieldValue, FormTemplateField)
                .join(
                    FormTemplateField,
                    FormTemplateField.id == FormFieldValue.form_template_field_id,
                )
                .where(FormFieldValue.form_instance_id == instance.id)
                .order_by(FormTemplateField.sort_order)
            )
        ).all()
        return {
            "id": str(instance.id),
            "instance_key": instance.instance_key,
            "compliance_case_id": str(instance.compliance_case_id),
            "form_template_id": str(instance.form_template_id),
            "version": instance.version,
            "status": instance.status,
            "signature_required": instance.signature_required,
            "signature_status": instance.signature_status,
            "required_signatory_actor": instance.required_signatory_actor,
            "signed_document_id": (
                str(instance.signed_document_id) if instance.signed_document_id else None
            ),
            "external_submission_reference": instance.external_submission_reference,
            "missing_fields": instance.missing_fields,
            "validation_results": instance.validation_results,
            "field_snapshot_sha256": instance.field_snapshot_sha256,
            "approved_draft_sha256": instance.approved_draft_sha256,
            "generated_document_id": (
                str(instance.generated_document_id) if instance.generated_document_id else None
            ),
            "worksheet_document_id": (
                str(instance.worksheet_document_id) if instance.worksheet_document_id else None
            ),
            "prepared_by_actor": instance.prepared_by_actor,
            "reviewed_by_actor": instance.reviewed_by_actor,
            "fields": [
                {
                    "field_key": field.field_key,
                    "label": field.label,
                    "field_type": field.field_type,
                    "required": field.required,
                    "sensitivity": field.sensitivity,
                    "page_number": field.page_number,
                    "status": row.status,
                    # Only the masked value is ever returned by the API.
                    "display_value": row.display_value_redacted,
                    "source_type": row.source_type,
                    "source_value_version": row.source_value_version,
                    "unresolved_reason": row.unresolved_reason,
                    "reviewed_by_actor": row.reviewed_by_actor,
                    "is_masked": row.value_encrypted is not None,
                }
                for row, field in rows
            ],
        }

    async def refresh_metrics(self) -> None:
        waiting = (
            await self.session.scalar(
                select(func.count())
                .select_from(FormInstance)
                .where(FormInstance.status == FormInstanceStatus.SIGNATURE_PENDING.value)
            )
            or 0
        )
        FORMS_WAITING_SIGNATURE.set(waiting)

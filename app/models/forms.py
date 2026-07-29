"""Form templates, field mappings, instances, and per-field values.

Boundaries encoded in this schema:

* ``signature_required`` and the ``SIGNATURE_REQUIRED`` field status record that a
  human must sign. There is no column for a generated signature image, because
  the system never produces one.
* ``signed_document_id`` is only populated from uploaded evidence, and
  ``approved_draft_sha256`` lets the service prove the signed copy corresponds to
  the approved draft rather than some other revision.
* ``SUBMITTED_EXTERNALLY`` is a record that a human submitted elsewhere. Nothing
  in this milestone performs a submission.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.forms.enums import (
    FieldDetectionStatus,
    FieldSourceType,
    FormFamily,
    FormFieldType,
    FormFieldValueStatus,
    FormFormat,
    FormInstanceStatus,
    FormTemplateStatus,
    MappingStatus,
    SignatureRequirementStatus,
)
from app.information_registry.enums import Sensitivity
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_check


class FormTemplate(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A registered, versioned blank form.

    The original template document is never modified. Filling always writes a new
    draft document so the pristine template stays available for the next cycle.
    """

    __tablename__ = "form_templates"
    __table_args__ = (
        UniqueConstraint("template_key", name="uq_form_templates_key"),
        Index("ix_form_templates_family", "form_family", "status"),
        Index("ix_form_templates_scope", "jurisdiction_id", "license_type_id"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="effective_range",
        ),
        enum_check("form_family", FormFamily, "family"),
        enum_check("form_format", FormFormat, "format"),
        enum_check("field_detection_status", FieldDetectionStatus, "detection"),
        enum_check("status", FormTemplateStatus, "status"),
    )

    template_key: Mapped[str] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    form_family: Mapped[str] = mapped_column(nullable=False)
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jurisdictions.id", ondelete="RESTRICT")
    )
    license_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("license_types.id", ondelete="RESTRICT")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: RESTRICT: the blank template must remain retrievable for any instance
    #: generated from it.
    template_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    form_format: Mapped[str] = mapped_column(nullable=False)
    field_detection_status: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    effective_from: Mapped[date | None]
    effective_to: Mapped[date | None]
    #: Populated by inspection; lets the UI warn when a template is re-uploaded
    #: with different fields.
    detected_field_count: Mapped[int | None] = mapped_column(Integer)
    template_sha256: Mapped[str | None]
    inspection_notes: Mapped[str | None]
    reviewed_by_actor: Mapped[str | None]
    reviewed_at: Mapped[datetime | None]
    supersedes_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_templates.id", ondelete="SET NULL")
    )


class FormTemplateField(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One inspected or manually declared field on a template."""

    __tablename__ = "form_template_fields"
    __table_args__ = (
        UniqueConstraint("form_template_id", "field_key", name="uq_form_template_fields_key"),
        Index("ix_form_template_fields_template", "form_template_id", "sort_order"),
        enum_check("field_type", FormFieldType, "type"),
        enum_check("sensitivity", Sensitivity, "sensitivity"),
    )

    form_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_templates.id", ondelete="CASCADE"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(nullable=False)
    #: Native AcroForm field name or DOCX placeholder token. NULL for worksheet
    #: rows on a flat PDF, where no machine-addressable field exists.
    native_field_name: Mapped[str | None]
    label: Mapped[str] = mapped_column(nullable=False)
    field_type: Mapped[str] = mapped_column(nullable=False)
    required: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    allowed_values: Mapped[list[Any] | None] = mapped_column(JSONB)
    page_number: Mapped[int | None] = mapped_column(Integer)
    instructions: Mapped[str | None]
    sensitivity: Mapped[str] = mapped_column(nullable=False)
    max_length: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))


class FormFieldMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How a template field is sourced from governed data.

    ``requires_review`` defaults true: a proposed mapping never auto-fills a real
    filing until someone confirms the field means what we think it means. This is
    the guard against "fill an unknown field by guessing".
    """

    __tablename__ = "form_field_mappings"
    __table_args__ = (
        # One active mapping per field; history is kept via RETIRED rows.
        Index(
            "uq_form_field_mappings_active",
            "form_template_field_id",
            unique=True,
            postgresql_where=text("mapping_status = 'APPROVED'"),
        ),
        Index("ix_form_field_mappings_field", "form_template_field_id", "mapping_status"),
        Index("ix_form_field_mappings_source", "source_type", "source_key"),
        enum_check("source_type", FieldSourceType, "source_type"),
        enum_check("mapping_status", MappingStatus, "status"),
    )

    form_template_field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_template_fields.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(nullable=False)
    #: Information definition key, entity attribute name, or calculation key.
    source_key: Mapped[str | None]
    #: Named, whitelisted transformation (e.g. UPPERCASE, DATE_MMDDYYYY). Never
    #: an executable expression.
    transformation: Mapped[str | None]
    mapping_status: Mapped[str] = mapped_column(nullable=False)
    requires_review: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    default_value: Mapped[str | None]
    notes: Mapped[str | None]
    approved_by_actor: Mapped[str | None]
    approved_at: Mapped[datetime | None]


class FormInstance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One prepared copy of a template for a specific compliance case."""

    __tablename__ = "form_instances"
    __table_args__ = (
        UniqueConstraint("instance_key", name="uq_form_instances_key"),
        UniqueConstraint(
            "compliance_case_id", "form_template_id", "version", name="uq_form_instances_version"
        ),
        Index("ix_form_instances_case", "compliance_case_id", "status"),
        Index("ix_form_instances_status", "status", "signature_required"),
        CheckConstraint("version >= 1", name="version"),
        enum_check("status", FormInstanceStatus, "status"),
        enum_check("signature_status", SignatureRequirementStatus, "signature_status"),
    )

    instance_key: Mapped[str] = mapped_column(nullable=False)
    compliance_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_cases.id", ondelete="CASCADE"), nullable=False
    )
    form_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_templates.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    #: The generated draft (never the template itself).
    generated_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    worksheet_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    #: Digest over the ordered field snapshot at generation time.
    field_snapshot_sha256: Mapped[str | None]
    #: Digest of the draft approved for signature; compared against the uploaded
    #: signed copy's provenance so an unrelated document cannot be passed off as
    #: the signed version of this draft.
    approved_draft_sha256: Mapped[str | None]
    missing_fields: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    validation_results: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    prepared_by_actor: Mapped[str | None]
    reviewed_by_actor: Mapped[str | None]
    reviewed_at: Mapped[datetime | None]
    signature_required: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    signature_status: Mapped[str] = mapped_column(
        nullable=False, server_default=text("'NOT_REQUIRED'")
    )
    #: Who must sign, recorded as a requirement only.
    required_signatory_actor: Mapped[str | None]
    required_signatory_title: Mapped[str | None]
    signed_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    signed_recorded_by_actor: Mapped[str | None]
    signed_recorded_at: Mapped[datetime | None]
    #: External submission is a *recorded human action*, never an automated one.
    external_submission_reference: Mapped[str | None]
    external_submission_recorded_by_actor: Mapped[str | None]
    external_submission_recorded_at: Mapped[datetime | None]
    generated_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    superseded_by_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_instances.id", ondelete="SET NULL")
    )
    rejection_reason: Mapped[str | None]


class FormFieldValue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One field's value on one instance, with provenance and review state.

    Values are encrypted with the same envelope scheme as the information
    registry, bound to ``form_field_value:<row id>``. ``display_value_redacted``
    is the only representation permitted in list views, logs, and telemetry.
    """

    __tablename__ = "form_field_values"
    __table_args__ = (
        UniqueConstraint(
            "form_instance_id", "form_template_field_id", name="uq_form_field_values_field"
        ),
        Index("ix_form_field_values_instance", "form_instance_id", "status"),
        enum_check("source_type", FieldSourceType, "source_type"),
        enum_check("status", FormFieldValueStatus, "status"),
    )

    form_instance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_instances.id", ondelete="CASCADE"), nullable=False
    )
    form_template_field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_template_fields.id", ondelete="RESTRICT"), nullable=False
    )
    value_encrypted: Mapped[str | None]
    #: Cleartext for INTERNAL-sensitivity fields only.
    value_plain: Mapped[str | None]
    display_value_redacted: Mapped[str | None]
    source_type: Mapped[str] = mapped_column(nullable=False)
    #: The information_value / license / case row the value came from.
    source_record_id: Mapped[uuid.UUID | None]
    #: Version of the information value consumed, pinned for audit.
    source_value_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(nullable=False)
    reviewed_by_actor: Mapped[str | None]
    reviewed_at: Mapped[datetime | None]
    #: Populated when the field could not be filled, e.g. STALE_INFORMATION_VALUE.
    unresolved_reason: Mapped[str | None]
    #: Links the gap to the internal request raised to close it.
    information_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("case_information_requests.id", ondelete="SET NULL")
    )

"""Reusable information definitions, versioned values, and usage audit.

Sensitive-data design
---------------------
``value_encrypted`` holds an AES-256-GCM envelope produced by
:mod:`app.core.crypto`, bound to ``information_value:<row id>`` as associated
data. Consequences that matter:

* A ciphertext copied into another row will not decrypt, so a restricted value
  cannot be silently re-pointed at a different entity.
* ``value_fingerprint`` is a keyed HMAC, letting the service detect "unchanged
  answer" without decrypting and without offering an offline guessing target.
* ``display_value_redacted`` is the only field safe for lists, logs, and
  exports. The plaintext never enters a log record, metric label, or AI prompt.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.information_registry.enums import (
    InformationCategory,
    InformationDataType,
    InformationValueStatus,
    ReusablePolicy,
    Sensitivity,
    UsagePurpose,
)
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_check


class InformationDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A recurring licensing question we expect to answer more than once."""

    __tablename__ = "information_definitions"
    __table_args__ = (
        Index("ix_information_definitions_category", "category", "sensitivity"),
        CheckConstraint(
            "freshness_days IS NULL OR freshness_days > 0",
            name="freshness_positive",
        ),
        enum_check("category", InformationCategory, "category"),
        enum_check("data_type", InformationDataType, "data_type"),
        enum_check("sensitivity", Sensitivity, "sensitivity"),
        enum_check("reusable_policy", ReusablePolicy, "reusable"),
    )

    information_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    category: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None]
    data_type: Mapped[str] = mapped_column(nullable=False)
    sensitivity: Mapped[str] = mapped_column(nullable=False)
    default_owner_role: Mapped[str | None]
    validation_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    reusable_policy: Mapped[str] = mapped_column(nullable=False)
    freshness_days: Mapped[int | None] = mapped_column(Integer)
    #: How many trailing characters may be revealed in a masked display value.
    display_keep_last: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class InformationValue(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One versioned answer, scoped to an entity and optionally a jurisdiction.

    ``legal_entity_id`` NULL means organization-wide, which is only permitted for
    definitions carrying ``ALL_ENTITIES_APPROVED`` and requires a manager
    approval record. Nothing becomes organization-wide by accident.
    """

    __tablename__ = "information_values"
    __table_args__ = (
        # One version number per (definition, entity, jurisdiction) scope.
        Index(
            "uq_information_values_version",
            "information_definition_id",
            text("COALESCE(legal_entity_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            text("COALESCE(jurisdiction_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "value_version",
            unique=True,
        ),
        # At most one APPROVED value per scope; supersession is explicit.
        Index(
            "uq_information_values_approved",
            "information_definition_id",
            text("COALESCE(legal_entity_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            text("COALESCE(jurisdiction_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
            postgresql_where=text("status = 'APPROVED'"),
        ),
        Index("ix_information_values_status", "status", "valid_to"),
        Index("ix_information_values_entity", "legal_entity_id", "status"),
        Index("ix_information_values_owner", "owner_actor", "status"),
        CheckConstraint("value_version >= 1", name="version"),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="validity_range",
        ),
        enum_check("status", InformationValueStatus, "status"),
    )

    information_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("information_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="CASCADE")
    )
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jurisdictions.id", ondelete="SET NULL")
    )
    license_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("license_inventory.id", ondelete="SET NULL")
    )
    vendor_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    compliance_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("compliance_cases.id", ondelete="SET NULL")
    )
    value_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: AES-GCM envelope. Always populated for RESTRICTED and above; also used for
    #: lower levels so one code path handles every value.
    value_encrypted: Mapped[str | None]
    #: Cleartext copy for INTERNAL values only, enabling search and export.
    value_plain: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    value_fingerprint: Mapped[str] = mapped_column(nullable=False)
    display_value_redacted: Mapped[str | None]
    status: Mapped[str] = mapped_column(nullable=False)
    valid_from: Mapped[date | None]
    valid_to: Mapped[date | None]
    owner_actor: Mapped[str | None]
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    source_reference: Mapped[str | None]
    created_by_actor: Mapped[str | None]
    approved_by_actor: Mapped[str | None]
    approved_at: Mapped[datetime | None]
    #: Manager approval required before a value may cross legal entities.
    cross_entity_approved_by_actor: Mapped[str | None]
    cross_entity_approved_at: Mapped[datetime | None]
    superseded_by_value_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("information_values.id", ondelete="SET NULL")
    )
    rejection_reason: Mapped[str | None]
    last_used_at: Mapped[datetime | None]


class InformationValueUsage(UUIDPrimaryKeyMixin, Base):
    """Every read of an approved value, for provenance and privacy audit."""

    __tablename__ = "information_value_usage"
    __table_args__ = (
        Index("ix_information_value_usage_value", "information_value_id", "used_at"),
        Index("ix_information_value_usage_case", "compliance_case_id"),
        Index("ix_information_value_usage_form", "form_instance_id"),
        enum_check("purpose", UsagePurpose, "purpose"),
    )

    information_value_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("information_values.id", ondelete="CASCADE"), nullable=False
    )
    compliance_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("compliance_cases.id", ondelete="SET NULL")
    )
    form_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_instances.id", ondelete="SET NULL")
    )
    packet_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_packets.id", ondelete="SET NULL")
    )
    used_by_actor: Mapped[str | None]
    purpose: Mapped[str] = mapped_column(nullable=False)
    #: Version actually consumed, so a later supersession never rewrites history.
    used_value_version: Mapped[int | None] = mapped_column(Integer)
    used_at: Mapped[datetime] = mapped_column(nullable=False)


class InformationOwnerAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Who stewards a definition, optionally narrowed to one legal entity."""

    __tablename__ = "information_owner_assignments"
    __table_args__ = (
        UniqueConstraint(
            "information_definition_id",
            "legal_entity_id",
            "owner_actor",
            name="uq_information_owner_assignments",
        ),
        Index("ix_information_owner_assignments_owner", "owner_actor", "is_active"),
    )

    information_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("information_definitions.id", ondelete="CASCADE"), nullable=False
    )
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="CASCADE")
    )
    owner_actor: Mapped[str] = mapped_column(nullable=False)
    is_primary: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    assigned_by_actor: Mapped[str | None]

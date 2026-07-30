"""Legal entities, operating profiles, license inventory, obligations, and cases.

The inventory here replaces the manual master-tracker spreadsheet. Two invariants
shape the schema:

* **Legal entities are isolated.** Every material row carries an explicit
  ``legal_entity_id``. Nothing is implicitly organization-wide.
* **Applicability and filing channel are orthogonal.** ``current_status`` says
  whether an authority exists; ``filing_channel`` says how it is transacted. An
  NMLS-managed licence can still carry paper obligations, so the two never
  collapse into one flag.
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
    Numeric,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.licensing.enums import LIVE_LICENSE_STATUSES as _LIVE
from app.licensing.enums import (
    ActivityCategory,
    BondChannel,
    BondStatus,
    CaseEmailLinkStatus,
    CaseInformationRequestStatus,
    CasePriority,
    CaseStage,
    CaseStatus,
    CaseType,
    EntityStatus,
    EntityType,
    FilingChannel,
    JurisdictionType,
    LicenseCategory,
    LicenseStatus,
    ObligationStatus,
    ObligationType,
    ProfileStatus,
    SourceConfidence,
)
from app.licensing.jobs import LicensingJobStatus
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_check


class LegalEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A distinct legal person that holds licences and files obligations.

    ``tax_identifier_reference`` is a *pointer* (vault path or registry key), not
    a tax identifier. Raw identifiers live in the encrypted information registry
    under a HIGHLY_RESTRICTED definition, never in this table.
    """

    __tablename__ = "legal_entities"
    __table_args__ = (
        Index("ix_legal_entities_status", "status", "is_in_scope"),
        enum_check("entity_type", EntityType, "entity_type"),
        enum_check("status", EntityStatus, "status"),
    )

    entity_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    legal_name: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[str | None]
    entity_type: Mapped[str] = mapped_column(nullable=False)
    formation_jurisdiction: Mapped[str | None]
    formation_date: Mapped[date | None]
    tax_identifier_reference: Mapped[str | None]
    nmls_id: Mapped[str | None]
    primary_business_address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    mailing_address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(nullable=False)
    is_in_scope: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    out_of_scope_reason: Mapped[str | None]


class BusinessActivity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Catalogue of activities that drive licensing applicability."""

    __tablename__ = "business_activities"
    __table_args__ = (enum_check("category", ActivityCategory, "category"),)

    activity_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None]
    category: Mapped[str] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class OperatingProfile(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Versioned snapshot of how an entity operates, used as assessment input.

    Versioning is what makes an assessment reproducible: a result records the
    profile version it consumed, so changing operations later never rewrites the
    history of a prior determination.
    """

    __tablename__ = "operating_profiles"
    __table_args__ = (
        UniqueConstraint(
            "legal_entity_id", "name", "version", name="uq_operating_profiles_version"
        ),
        # Exactly one ACTIVE version per (entity, profile name).
        Index(
            "uq_operating_profiles_active",
            "legal_entity_id",
            "name",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="effective_range",
        ),
        enum_check("status", ProfileStatus, "status"),
    )

    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    effective_from: Mapped[date | None]
    effective_to: Mapped[date | None]
    facts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    approved_by_actor: Mapped[str | None]
    approved_at: Mapped[datetime | None]


class Jurisdiction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Federal, state, territory, or local jurisdiction, hierarchically linked."""

    __tablename__ = "jurisdictions"
    __table_args__ = (
        Index("ix_jurisdictions_parent", "parent_jurisdiction_id"),
        enum_check("jurisdiction_type", JurisdictionType, "type"),
    )

    jurisdiction_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    jurisdiction_type: Mapped[str] = mapped_column(nullable=False)
    parent_jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jurisdictions.id", ondelete="SET NULL")
    )
    timezone: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class LicenseType(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Catalogue of licence, registration, bond, and report types."""

    __tablename__ = "license_types"
    __table_args__ = (enum_check("category", LicenseCategory, "category"),)

    license_type_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    category: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class LicenseInventory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Central licence inventory: the system of record replacing the tracker."""

    __tablename__ = "license_inventory"
    __table_args__ = (
        # One live authority per entity/jurisdiction/type unless the row is
        # explicitly flagged as representing an additional authority (multiple
        # branch or dual-authority licences).
        Index(
            "uq_license_inventory_live_authority",
            "legal_entity_id",
            "jurisdiction_id",
            "license_type_id",
            unique=True,
            postgresql_where=text(
                "represents_additional_authority = false AND current_status IN ("
                + ", ".join(f"'{status}'" for status in _LIVE)
                + ")"
            ),
        ),
        Index("ix_license_inventory_entity", "legal_entity_id", "current_status"),
        Index("ix_license_inventory_expiration", "expiration_date"),
        Index("ix_license_inventory_renewal_due", "renewal_due_date"),
        Index("ix_license_inventory_jurisdiction", "jurisdiction_id", "license_type_id"),
        CheckConstraint(
            "expiration_date IS NULL OR issue_date IS NULL OR expiration_date >= issue_date",
            name="date_sequence",
        ),
        enum_check("current_status", LicenseStatus, "status"),
        enum_check("filing_channel", FilingChannel, "filing_channel"),
        enum_check("source_confidence", SourceConfidence, "confidence"),
    )

    license_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="RESTRICT"), nullable=False
    )
    jurisdiction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False
    )
    license_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("license_types.id", ondelete="RESTRICT"), nullable=False
    )
    regulator_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    vendor_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    license_number: Mapped[str | None]
    nmls_license_id: Mapped[str | None]
    filing_channel: Mapped[str] = mapped_column(nullable=False)
    current_status: Mapped[str] = mapped_column(nullable=False)
    #: True when this row deliberately coexists with another live licence for the
    #: same entity/jurisdiction/type (branch licences, dual authorities).
    represents_additional_authority: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    authority_label: Mapped[str | None]
    issue_date: Mapped[date | None]
    effective_date: Mapped[date | None]
    expiration_date: Mapped[date | None]
    renewal_due_date: Mapped[date | None]
    internal_start_date: Mapped[date | None]
    surrender_date: Mapped[date | None]
    next_review_date: Mapped[date | None]
    responsible_owner: Mapped[str | None]
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None]
    source_confidence: Mapped[str] = mapped_column(nullable=False)
    last_verified_at: Mapped[datetime | None]


class LicenseStatusEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only licence status history. Never updated or deleted."""

    __tablename__ = "license_status_events"
    __table_args__ = (
        Index("ix_license_status_events_license", "license_id", "occurred_at"),
        enum_check("to_status", LicenseStatus, "to_status"),
    )

    license_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("license_inventory.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None]
    to_status: Mapped[str] = mapped_column(nullable=False)
    effective_at: Mapped[datetime] = mapped_column(nullable=False)
    actor_id: Mapped[str | None]
    source_type: Mapped[str | None]
    source_reference: Mapped[str | None]
    note: Mapped[str | None]
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)


class LicenseBond(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Surety bond attached to a licence.

    Modelled separately from ``license_inventory`` because a bond has its own
    provider, number, amount, and expiry, and its own renewal cadence that may
    not match the licence. ``bond_channel`` distinguishes NMLS Electronic Surety
    Bond records from paper originals and vendor-managed processes, which follow
    materially different operational steps.
    """

    __tablename__ = "license_bonds"
    __table_args__ = (
        Index("ix_license_bonds_license", "license_id", "status"),
        Index("ix_license_bonds_expiration", "expiration_date"),
        CheckConstraint(
            "expiration_date IS NULL OR effective_date IS NULL "
            "OR expiration_date >= effective_date",
            name="date_sequence",
        ),
        CheckConstraint("amount IS NULL OR amount >= 0", name="amount_non_negative"),
        enum_check("status", BondStatus, "status"),
        enum_check("bond_channel", BondChannel, "channel"),
    )

    bond_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="RESTRICT"), nullable=False
    )
    license_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("license_inventory.id", ondelete="SET NULL")
    )
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jurisdictions.id", ondelete="SET NULL")
    )
    bond_provider_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    bond_number: Mapped[str | None]
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(nullable=False, server_default=text("'USD'"))
    status: Mapped[str] = mapped_column(nullable=False)
    bond_channel: Mapped[str] = mapped_column(nullable=False)
    effective_date: Mapped[date | None]
    expiration_date: Mapped[date | None]
    continuous: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    cancellation_notice_date: Mapped[date | None]
    bond_form_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    rider_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    continuation_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    responsible_owner: Mapped[str | None]
    notes: Mapped[str | None]
    last_verified_at: Mapped[datetime | None]


class ComplianceObligation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A recurring or one-off duty: renewal, bond, report, or other filing.

    Obligations outlive email threads on purpose. A financial statement still
    outstanding after a conversation ends remains visible here.
    """

    __tablename__ = "compliance_obligations"
    __table_args__ = (
        Index("ix_compliance_obligations_due", "next_due_date", "status"),
        Index("ix_compliance_obligations_entity", "legal_entity_id", "status"),
        Index("ix_compliance_obligations_license", "license_id"),
        Index("ix_compliance_obligations_type", "obligation_type", "status"),
        enum_check("obligation_type", ObligationType, "type"),
        enum_check("status", ObligationStatus, "status"),
    )

    obligation_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="RESTRICT"), nullable=False
    )
    license_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("license_inventory.id", ondelete="SET NULL")
    )
    bond_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("license_bonds.id", ondelete="SET NULL")
    )
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jurisdictions.id", ondelete="SET NULL")
    )
    obligation_type: Mapped[str] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    recurrence_rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    statutory_due_date: Mapped[date | None]
    next_due_date: Mapped[date | None]
    internal_start_date: Mapped[date | None]
    responsible_owner: Mapped[str | None]
    vendor_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    regulator_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    #: Snapshot ids backing this obligation's timing. Stored as an array because
    #: obligations cite sources for provenance only; rule-level citations use the
    #: normalized requirement_rule_sources table where integrity matters.
    requirement_source_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    #: Set when this obligation was generated from a completed prior cycle.
    predecessor_obligation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("compliance_obligations.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None]


class ComplianceCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The operational workspace that carries an obligation to completion."""

    __tablename__ = "compliance_cases"
    __table_args__ = (
        Index("ix_compliance_cases_stage", "current_stage", "status"),
        Index("ix_compliance_cases_entity", "legal_entity_id", "status"),
        Index("ix_compliance_cases_obligation", "obligation_id"),
        Index("ix_compliance_cases_owner", "assigned_owner", "status"),
        Index("ix_compliance_cases_target", "internal_target_date"),
        enum_check("case_type", CaseType, "type"),
        enum_check("current_stage", CaseStage, "stage"),
        enum_check("status", CaseStatus, "status"),
        enum_check("priority", CasePriority, "priority"),
    )

    case_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    obligation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_obligations.id", ondelete="RESTRICT"), nullable=False
    )
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="RESTRICT"), nullable=False
    )
    license_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("license_inventory.id", ondelete="SET NULL")
    )
    bond_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("license_bonds.id", ondelete="SET NULL")
    )
    #: Bridges to the Milestone 4 task board so email-driven work and
    #: calendar-driven work share one operational surface.
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("licensing_tasks.id", ondelete="SET NULL")
    )
    case_type: Mapped[str] = mapped_column(nullable=False)
    current_stage: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    priority: Mapped[str] = mapped_column(nullable=False)
    statutory_due_date: Mapped[date | None]
    internal_target_date: Mapped[date | None]
    assigned_owner: Mapped[str | None]
    vendor_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    regulator_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    primary_conversation_id: Mapped[str | None]
    #: Free-text reason recorded when a case is closed without renewed evidence.
    close_reason: Mapped[str | None]
    blocked_reason: Mapped[str | None]
    created_by_actor: Mapped[str | None]
    stage_entered_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]


class ComplianceCaseStageEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only stage history with the evidence that justified each move."""

    __tablename__ = "compliance_case_stage_events"
    __table_args__ = (
        Index("ix_case_stage_events_case", "compliance_case_id", "occurred_at"),
        enum_check("to_stage", CaseStage, "ck_case_stage_events_to_stage"),
    )

    compliance_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_cases.id", ondelete="CASCADE"), nullable=False
    )
    from_stage: Mapped[str | None]
    to_stage: Mapped[str] = mapped_column(nullable=False)
    actor_id: Mapped[str | None]
    reason: Mapped[str | None]
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: Seconds spent in ``from_stage``; lets dashboards report cycle time without
    #: recomputing from the whole event stream.
    seconds_in_previous_stage: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)


class CaseEmailLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Correspondence attached to a compliance case, and who vouched for it.

    The system proposes a link when a reviewed licensing email looks like it
    belongs to an open case; a person confirms or rejects it. Only a CONFIRMED
    link is treated as the case's correspondence, because attaching one legal
    entity's thread to another entity's case is a reportable error, not a
    display glitch. The match signals are stored so a reviewer can see *why*
    a link was proposed rather than being asked to trust a score.
    """

    __tablename__ = "case_email_links"
    __table_args__ = (
        UniqueConstraint("compliance_case_id", "email_id", name="uq_case_email_link"),
        Index("ix_case_email_links_case", "compliance_case_id", "link_status"),
        Index("ix_case_email_links_status", "link_status", "proposed_at"),
        Index("ix_case_email_links_conversation", "conversation_id"),
        enum_check("link_status", CaseEmailLinkStatus, "ck_case_email_links_status"),
    )

    compliance_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_cases.id", ondelete="CASCADE"), nullable=False
    )
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    #: Graph conversation the email belongs to. Copied at link time so the
    #: thread stays resolvable even if the message row is later archived.
    conversation_id: Mapped[str | None]
    link_status: Mapped[str] = mapped_column(nullable=False)
    #: 0..1 confidence from the matcher. Advisory only: it orders the review
    #: queue and never authorises a link on its own.
    match_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    #: Human-readable signals, e.g. ["license number 12345 matched", "vendor matched"].
    match_reasons: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    proposed_by_actor: Mapped[str | None]
    proposed_at: Mapped[datetime] = mapped_column(nullable=False)
    decided_by_actor: Mapped[str | None]
    decided_at: Mapped[datetime | None]
    decision_reason: Mapped[str | None]


class CaseInformationRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A question that must be answered before the case can advance.

    Sources are tracked explicitly: ``source_vendor_question`` preserves the
    vendor's own wording, while ``information_definition_id`` links the question
    to a reusable registry definition so the answer can be reused next cycle.
    """

    __tablename__ = "case_information_requests"
    __table_args__ = (
        Index("ix_case_information_requests_case", "compliance_case_id", "status"),
        Index("ix_case_information_requests_assignee", "requested_from_actor", "status"),
        Index("ix_case_information_requests_due", "due_at"),
        enum_check("status", CaseInformationRequestStatus, "status"),
    )

    compliance_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_cases.id", ondelete="CASCADE"), nullable=False
    )
    information_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("information_definitions.id", ondelete="SET NULL")
    )
    question_text: Mapped[str] = mapped_column(nullable=False)
    requested_from_actor: Mapped[str | None]
    status: Mapped[str] = mapped_column(nullable=False)
    due_at: Mapped[datetime | None]
    response_value_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("information_values.id", ondelete="SET NULL")
    )
    source_email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL")
    )
    source_vendor_question: Mapped[str | None]
    #: Set when the answer was supplied to the vendor, for audit completeness.
    provided_to_vendor_at: Mapped[datetime | None]
    resolution_note: Mapped[str | None]


class LicensingNotification(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Internal portal notification.

    Milestone 6 never emails an external vendor directly. Notifications are
    internal records; outbound correspondence still flows through the Milestone 5
    controlled send workflow.
    """

    __tablename__ = "licensing_notifications"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_licensing_notifications_idem"),
        Index("ix_licensing_notifications_recipient", "recipient_actor", "read_at"),
        Index("ix_licensing_notifications_entity", "entity_type", "entity_id"),
    )

    notification_type: Mapped[str] = mapped_column(nullable=False)
    severity: Mapped[str] = mapped_column(nullable=False)
    recipient_actor: Mapped[str] = mapped_column(nullable=False)
    escalation_level: Mapped[str | None]
    title: Mapped[str] = mapped_column(nullable=False)
    body: Mapped[str | None]
    entity_type: Mapped[str] = mapped_column(nullable=False)
    entity_id: Mapped[str] = mapped_column(nullable=False)
    #: Deterministic key so repeated escalation sweeps do not spam an owner.
    idempotency_key: Mapped[str] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    read_at: Mapped[datetime | None]
    acknowledged_at: Mapped[datetime | None]


class LicensingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Leased PostgreSQL queue for licensing background work."""

    __tablename__ = "licensing_jobs"
    __table_args__ = (
        Index("ix_licensing_jobs_claim", "status", "available_at", "priority"),
        Index("ix_licensing_jobs_type", "job_type", "status"),
        enum_check("status", LicensingJobStatus, "status"),
    )

    job_type: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    idempotency_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="CASCADE")
    )
    compliance_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("compliance_cases.id", ondelete="CASCADE")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("6"))
    available_at: Mapped[datetime] = mapped_column(nullable=False)
    lease_owner: Mapped[str | None]
    lease_expires_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    last_error_code: Mapped[str | None]
    last_error_message: Mapped[str | None]
    correlation_id: Mapped[uuid.UUID | None]

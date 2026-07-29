"""Requirement sources, versioned rules, and advisory assessment results.

Governance invariants encoded here:

* No rule exists without source provenance — ``requirement_rule_sources`` is a
  normalized link table with real foreign keys, so a cited snapshot cannot be
  deleted out from under an active rule.
* Sources are versioned. A changed webpage or checklist creates a new snapshot in
  ``PENDING_REVIEW``; it never mutates the approved one.
* Results are immutable advisory records carrying facts used, facts missing,
  matched rules, citations, freshness, and review state.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_check
from app.requirements.taxonomy import (
    AssessmentStatus,
    AssessmentType,
    AuthorityLevel,
    OverrideAuthority,
    RequirementOutcome,
    RuleSetStatus,
    SnapshotReviewStatus,
    SourceAccessMethod,
    SourceFreshnessStatus,
    SourceType,
    SourceVerificationStatus,
)


class RequirementSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An authority we rely on: statute, regulation, checklist, memo, or guidance.

    ``authority_level`` is what separates law from operational advice. A vendor
    checklist may drive a case but can never, on its own, establish a legal
    requirement.
    """

    __tablename__ = "requirement_sources"
    __table_args__ = (
        Index("ix_requirement_sources_jurisdiction", "jurisdiction_id", "source_type"),
        Index("ix_requirement_sources_verification", "verification_status", "last_verified_at"),
        enum_check("source_type", SourceType, "type"),
        enum_check("authority_level", AuthorityLevel, "authority"),
        enum_check("access_method", SourceAccessMethod, "access"),
        enum_check("verification_status", SourceVerificationStatus, "verification"),
    )

    source_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(nullable=False)
    authority_level: Mapped[str] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(nullable=False)
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jurisdictions.id", ondelete="SET NULL")
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    official_url: Mapped[str | None]
    access_method: Mapped[str] = mapped_column(nullable=False)
    effective_date: Mapped[date | None]
    expiry_date: Mapped[date | None]
    last_verified_at: Mapped[datetime | None]
    verification_status: Mapped[str] = mapped_column(nullable=False)
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "requirement_source_snapshots.id",
            name="fk_requirement_sources_current_snapshot",
            ondelete="SET NULL",
            use_alter=True,
        )
    )
    owner_actor: Mapped[str | None]
    #: Per-source override of the global freshness policy, in days.
    freshness_days: Mapped[int | None] = mapped_column(Integer)
    citation_label: Mapped[str | None]
    notes: Mapped[str | None]


class RequirementSourceSnapshot(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable point-in-time capture of a source's content."""

    __tablename__ = "requirement_source_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "requirement_source_id", "version", name="uq_requirement_source_snapshots_version"
        ),
        Index("ix_requirement_source_snapshots_review", "review_status", "retrieved_at"),
        Index("ix_requirement_source_snapshots_hash", "content_sha256"),
        CheckConstraint("version >= 1", name="version"),
        enum_check("review_status", SnapshotReviewStatus, "review"),
    )

    requirement_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement_sources.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_storage_uri: Mapped[str | None]
    content_sha256: Mapped[str] = mapped_column(nullable=False)
    extracted_text_storage_uri: Mapped[str | None]
    retrieved_at: Mapped[datetime] = mapped_column(nullable=False)
    effective_date: Mapped[date | None]
    change_summary: Mapped[str | None]
    #: Structured diff against the previous snapshot: added, removed, changed.
    change_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    previous_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("requirement_source_snapshots.id", ondelete="SET NULL")
    )
    review_status: Mapped[str] = mapped_column(nullable=False)
    reviewed_by_actor: Mapped[str | None]
    reviewed_at: Mapped[datetime | None]
    review_notes: Mapped[str | None]
    #: True when a reviewer judged that the change affects live requirement rules.
    affects_rules: Mapped[bool | None]


class RequirementRuleSet(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A named, versioned collection of rules. Exactly one ACTIVE per name."""

    __tablename__ = "requirement_rule_sets"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_requirement_rule_sets_version"),
        Index(
            "uq_requirement_rule_sets_active",
            "name",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        CheckConstraint("version >= 1", name="version"),
        enum_check("status", RuleSetStatus, "status"),
    )

    name: Mapped[str] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None]
    approved_by_actor: Mapped[str | None]
    activated_at: Mapped[datetime | None]
    #: Set when this version was created in response to a source change.
    derived_from_rule_set_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("requirement_rule_sets.id", ondelete="SET NULL")
    )
    retired_at: Mapped[datetime | None]


class RequirementRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One conditional rule evaluated against operating-profile facts.

    ``conditions`` holds a constrained declarative DSL (see
    :mod:`app.requirements.conditions`). It is never executed as Python or SQL.
    """

    __tablename__ = "requirement_rules"
    __table_args__ = (
        UniqueConstraint("rule_set_id", "rule_key", name="uq_requirement_rules_key"),
        Index("ix_requirement_rules_scope", "rule_set_id", "jurisdiction_id", "license_type_id"),
        Index("ix_requirement_rules_enabled", "rule_set_id", "enabled", "priority"),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="effective_range",
        ),
        enum_check("outcome", RequirementOutcome, "outcome"),
    )

    rule_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement_rule_sets.id", ondelete="CASCADE"), nullable=False
    )
    rule_key: Mapped[str] = mapped_column(nullable=False)
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jurisdictions.id", ondelete="RESTRICT")
    )
    license_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("license_types.id", ondelete="RESTRICT")
    )
    conditions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    outcome: Mapped[str] = mapped_column(nullable=False)
    explanation_template: Mapped[str] = mapped_column(nullable=False)
    #: Lower numbers win. Specific jurisdiction/type rules are authored with
    #: lower priority values than broad catch-all rules.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    #: Filing channels this rule implies, e.g. NMLS plus a state supplement.
    filing_channels: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    #: Facts the rule needs; absent facts drive INSUFFICIENT_INFORMATION and are
    #: surfaced to the operator as "missing facts".
    required_facts: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    effective_from: Mapped[date | None]
    effective_to: Mapped[date | None]
    requires_counsel_review: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    notes: Mapped[str | None]
    retired_by_actor: Mapped[str | None]
    retired_reason: Mapped[str | None]


class RequirementRuleSource(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Normalized citation link between a rule and the snapshot backing it.

    A link table rather than an array column: real foreign keys guarantee every
    active rule keeps a resolvable citation, which is the whole point of source
    governance.
    """

    __tablename__ = "requirement_rule_sources"
    __table_args__ = (
        UniqueConstraint(
            "requirement_rule_id",
            "requirement_source_snapshot_id",
            name="uq_requirement_rule_sources_pair",
        ),
        Index("ix_requirement_rule_sources_snapshot", "requirement_source_snapshot_id"),
    )

    requirement_rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement_rules.id", ondelete="CASCADE"), nullable=False
    )
    requirement_source_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement_source_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    #: Optional pinpoint citation within the source (section, page, item number).
    citation_detail: Mapped[str | None]
    is_primary: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))


class RequirementAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One advisory evaluation run over a set of jurisdictions."""

    __tablename__ = "requirement_assessments"
    __table_args__ = (
        Index("ix_requirement_assessments_entity", "legal_entity_id", "status"),
        Index("ix_requirement_assessments_fingerprint", "input_fingerprint"),
        enum_check("assessment_type", AssessmentType, "type"),
        enum_check("status", AssessmentStatus, "status"),
    )

    assessment_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="CASCADE"), nullable=False
    )
    operating_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operating_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    assessment_type: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    requested_jurisdictions: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    input_facts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: Digest of (profile version, facts, rule-set version, jurisdictions). Lets
    #: the UI show "inputs changed since this result was approved".
    input_fingerprint: Mapped[str] = mapped_column(nullable=False)
    rule_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement_rule_sets.id", ondelete="RESTRICT"), nullable=False
    )
    #: Date the rules were resolved against, so effective-dated rules replay.
    effective_date: Mapped[date | None]
    created_by_actor: Mapped[str] = mapped_column(nullable=False)
    reviewed_by_actor: Mapped[str | None]
    reviewed_at: Mapped[datetime | None]
    review_notes: Mapped[str | None]
    evaluated_at: Mapped[datetime | None]
    superseded_by_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("requirement_assessments.id", ondelete="SET NULL")
    )


class RequirementAssessmentResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable advisory result for one jurisdiction/licence-type pair.

    ``requires_human_review`` defaults to true and is the gate on every
    downstream action. An unreviewed result is never a determination.
    """

    __tablename__ = "requirement_assessment_results"
    __table_args__ = (
        # COALESCE keeps the uniqueness meaningful when license_type_id is NULL
        # (a jurisdiction-level answer), which a plain UNIQUE would not.
        Index(
            "uq_requirement_assessment_results_scope",
            "assessment_id",
            "jurisdiction_id",
            text("COALESCE(license_type_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
        ),
        Index("ix_requirement_results_outcome", "assessment_id", "outcome"),
        Index("ix_requirement_results_review", "requires_human_review", "outcome"),
        enum_check("outcome", RequirementOutcome, "ck_requirement_results_outcome"),
        enum_check(
            "source_freshness_status", SourceFreshnessStatus, "ck_requirement_results_freshness"
        ),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement_assessments.id", ondelete="CASCADE"), nullable=False
    )
    jurisdiction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False
    )
    license_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("license_types.id", ondelete="RESTRICT")
    )
    outcome: Mapped[str] = mapped_column(nullable=False)
    filing_channels: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    explanation: Mapped[str] = mapped_column(nullable=False)
    facts_used: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    missing_facts: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    matched_rule_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    #: Denormalized citation payload: title, authority level, url, verified date,
    #: snapshot version. Denormalized on purpose so an approved result renders
    #: exactly as it did at approval time even if a source is later retired.
    source_citations: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    source_freshness_status: Mapped[str] = mapped_column(nullable=False)
    #: Records rules that disagreed, so a conflict is visible rather than hidden
    #: behind whichever rule happened to win on priority.
    conflicting_rule_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    requires_human_review: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    requires_counsel_review: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    reviewed_outcome: Mapped[str | None]
    reviewer_notes: Mapped[str | None]
    reviewed_by_actor: Mapped[str | None]
    reviewed_at: Mapped[datetime | None]


class AssessmentOverride(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A human decision that supersedes a computed outcome.

    Overrides expire. ``valid_to`` in the past means the override no longer
    applies and the underlying advisory outcome governs again, which forces
    periodic re-justification rather than permanent silent exceptions.
    """

    __tablename__ = "assessment_overrides"
    __table_args__ = (
        Index("ix_assessment_overrides_result", "assessment_result_id", "created_at"),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="validity_range",
        ),
        enum_check("original_outcome", RequirementOutcome, "original"),
        enum_check("overridden_outcome", RequirementOutcome, "overridden"),
        enum_check("authority", OverrideAuthority, "authority"),
    )

    assessment_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement_assessment_results.id", ondelete="CASCADE"), nullable=False
    )
    original_outcome: Mapped[str] = mapped_column(nullable=False)
    overridden_outcome: Mapped[str] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(nullable=False)
    authority: Mapped[str] = mapped_column(nullable=False)
    approved_by_actor: Mapped[str] = mapped_column(nullable=False)
    source_reference: Mapped[str | None]
    valid_from: Mapped[date | None]
    valid_to: Mapped[date | None]
    revoked_at: Mapped[datetime | None]
    revoked_by_actor: Mapped[str | None]

"""Milestone 4 identity, configuration, classification-run, and correction records."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UserPrincipal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_principals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "object_id", name="uq_user_principals_tenant_object"),
    )
    tenant_id: Mapped[str] = mapped_column(nullable=False)
    object_id: Mapped[str] = mapped_column(nullable=False)
    user_principal_name: Mapped[str | None]
    email: Mapped[str | None]
    display_name: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    first_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(nullable=False)


class UserRoleSnapshot(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "user_role_snapshots"
    user_principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_principals.id", ondelete="CASCADE"), nullable=False
    )
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{}'")
    )
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{}'")
    )
    source: Mapped[str] = mapped_column(nullable=False)
    observed_at: Mapped[datetime] = mapped_column(nullable=False)


class UserPreference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_preferences"
    user_principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_principals.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    timezone: Mapped[str | None]
    default_queue: Mapped[str | None]
    page_size: Mapped[int | None] = mapped_column(Integer)
    dashboard_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    notification_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"
    canonical_name: Mapped[str] = mapped_column(nullable=False)
    organization_type: Mapped[str] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    organization_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class OrganizationDomain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_domains"
    __table_args__ = (UniqueConstraint("domain", name="uq_organization_domains_domain"),)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(nullable=False)
    match_subdomains: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    trust_level: Mapped[str] = mapped_column(nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str | None]


class OrganizationAddress(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_addresses"
    __table_args__ = (UniqueConstraint("email_address", name="uq_organization_addresses_email"),)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email_address: Mapped[str] = mapped_column(nullable=False)
    trust_level: Mapped[str] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class ClassificationRuleSet(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "classification_rule_sets"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_classification_rule_sets_name_version"),
        Index(
            "uq_classification_rule_sets_active",
            "name",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )
    name: Mapped[str] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None]
    created_by_actor: Mapped[str | None]
    approved_by_actor: Mapped[str | None]
    activated_at: Mapped[datetime | None]


class ClassificationRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "classification_rules"
    __table_args__ = (
        UniqueConstraint("rule_set_id", "rule_key", name="uq_classification_rules_set_key"),
    )
    rule_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classification_rule_sets.id", ondelete="CASCADE"), nullable=False
    )
    rule_key: Mapped[str] = mapped_column(nullable=False)
    rule_type: Mapped[str] = mapped_column(nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    description: Mapped[str | None]


class PromptVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("prompt_key", "version", name="uq_prompt_versions_key_version"),
        Index(
            "uq_prompt_versions_active",
            "prompt_key",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )
    prompt_key: Mapped[str] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(nullable=False)
    model_constraints: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    input_template: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(nullable=False)
    created_by_actor: Mapped[str | None]
    approved_by_actor: Mapped[str | None]
    activated_at: Mapped[datetime | None]


class ClassificationRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "classification_runs"
    __table_args__ = (Index("ix_classification_runs_email_started", "email_id", "started_at"),)
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    classification_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classifications.id", ondelete="SET NULL")
    )
    job_id: Mapped[uuid.UUID | None]
    run_type: Mapped[str] = mapped_column(nullable=False)
    rule_set_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classification_rule_sets.id", ondelete="SET NULL")
    )
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL")
    )
    provider: Mapped[str | None]
    model: Mapped[str | None]
    status: Mapped[str] = mapped_column(nullable=False)
    deterministic_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    merged_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_errors: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    input_fingerprint: Mapped[str] = mapped_column(nullable=False)
    prompt_fingerprint: Mapped[str | None]
    provider_request_id: Mapped[str | None]
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[datetime | None]
    error_code: Mapped[str | None]
    error_message: Mapped[str | None]


class ClassificationFieldCorrection(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "classification_field_corrections"
    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classification_reviews.id", ondelete="CASCADE"), nullable=False
    )
    field_path: Mapped[str] = mapped_column(nullable=False)
    machine_value: Mapped[Any | None] = mapped_column(JSONB)
    reviewed_value: Mapped[Any | None] = mapped_column(JSONB)
    correction_reason: Mapped[str | None]

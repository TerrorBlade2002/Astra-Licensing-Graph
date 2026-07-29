"""Licensing lifecycle: inventory, requirement matrix, deadlines, registry,
packets, forms, and controlled tracker imports.

Adds the Milestone 6 schema in 40 tables. Notable choices, reviewed rather than
accepted as-generated:

* Partial unique indexes enforce "one live authority per entity/jurisdiction/
  licence type" and "one APPROVED information value per scope" without blocking
  historical or superseded rows.
* Expression indexes over ``COALESCE(<nullable fk>, <zero uuid>)`` make scope
  uniqueness meaningful when a scope column is NULL, which a plain UNIQUE would
  silently permit to duplicate.
* Citation links (``requirement_rule_sources``) and packet item documents use
  ``ON DELETE RESTRICT`` so an approved manifest or an active rule can never lose
  the evidence it depends on.

Revision ID: 0006_licensing_lifecycle
Revises: 0005_controlled_communications
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_licensing_lifecycle"
down_revision: str | None = "0005_controlled_communications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "business_activities",
        sa.Column("activity_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('COLLECTION', 'SERVICING', 'PURCHASING', 'COMMUNICATION', 'PAYMENT', 'LEGAL', 'REPORTING', 'SUPPORT', 'OTHER')",
            name=op.f("ck_business_activities_category"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_business_activities")),
        sa.UniqueConstraint("activity_key", name=op.f("uq_business_activities_activity_key")),
    )
    op.create_table(
        "information_definitions",
        sa.Column("information_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("data_type", sa.Text(), nullable=False),
        sa.Column("sensitivity", sa.Text(), nullable=False),
        sa.Column("default_owner_role", sa.Text(), nullable=True),
        sa.Column(
            "validation_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("reusable_policy", sa.Text(), nullable=False),
        sa.Column("freshness_days", sa.Integer(), nullable=True),
        sa.Column("display_keep_last", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('CONTACT_INFORMATION', 'CORPORATE_INFORMATION', 'OFFICER_INFORMATION', 'OWNERSHIP_INFORMATION', 'POLICY_INFORMATION', 'FINANCIAL_INFORMATION', 'LICENSING_INFORMATION', 'BOND_INFORMATION', 'OPERATIONAL_INFORMATION', 'ATTESTATION', 'SIGNATURE_INFORMATION')",
            name=op.f("ck_information_definitions_category"),
        ),
        sa.CheckConstraint(
            "data_type IN ('TEXT', 'LONG_TEXT', 'INTEGER', 'DECIMAL', 'BOOLEAN', 'DATE', 'EMAIL', 'PHONE', 'URL', 'ADDRESS', 'CURRENCY', 'ENUM', 'JSON', 'DOCUMENT_REFERENCE')",
            name=op.f("ck_information_definitions_data_type"),
        ),
        sa.CheckConstraint(
            "reusable_policy IN ('ENTITY_ONLY', 'ENTITY_AND_JURISDICTION', 'LICENSE_SPECIFIC', 'VENDOR_SPECIFIC', 'CASE_SPECIFIC', 'ALL_ENTITIES_APPROVED', 'NOT_REUSABLE')",
            name=op.f("ck_information_definitions_reusable"),
        ),
        sa.CheckConstraint(
            "sensitivity IN ('INTERNAL', 'CONFIDENTIAL', 'RESTRICTED', 'HIGHLY_RESTRICTED')",
            name=op.f("ck_information_definitions_sensitivity"),
        ),
        sa.CheckConstraint(
            "freshness_days IS NULL OR freshness_days > 0",
            name=op.f("ck_information_definitions_freshness_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_information_definitions")),
        sa.UniqueConstraint(
            "information_key", name=op.f("uq_information_definitions_information_key")
        ),
    )
    op.create_index(
        "ix_information_definitions_category",
        "information_definitions",
        ["category", "sensitivity"],
        unique=False,
    )
    op.create_table(
        "jurisdictions",
        sa.Column("jurisdiction_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("jurisdiction_type", sa.Text(), nullable=False),
        sa.Column("parent_jurisdiction_id", sa.UUID(), nullable=True),
        sa.Column("timezone", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jurisdiction_type IN ('FEDERAL', 'STATE', 'TERRITORY', 'COUNTY', 'CITY', 'OTHER_LOCAL')",
            name=op.f("ck_jurisdictions_type"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_jurisdiction_id"],
            ["jurisdictions.id"],
            name=op.f("fk_jurisdictions_parent_jurisdiction_id_jurisdictions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jurisdictions")),
        sa.UniqueConstraint("jurisdiction_key", name=op.f("uq_jurisdictions_jurisdiction_key")),
    )
    op.create_index(
        "ix_jurisdictions_parent", "jurisdictions", ["parent_jurisdiction_id"], unique=False
    )
    op.create_table(
        "legal_entities",
        sa.Column("entity_key", sa.Text(), nullable=False),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("formation_jurisdiction", sa.Text(), nullable=True),
        sa.Column("formation_date", sa.Date(), nullable=True),
        sa.Column("tax_identifier_reference", sa.Text(), nullable=True),
        sa.Column("nmls_id", sa.Text(), nullable=True),
        sa.Column(
            "primary_business_address", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("mailing_address", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("is_in_scope", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("out_of_scope_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_type IN ('CORPORATION', 'LLC', 'LP', 'LLP', 'PARTNERSHIP', 'SOLE_PROPRIETORSHIP', 'TRUST', 'OTHER')",
            name=op.f("ck_legal_entities_entity_type"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'DISSOLVED', 'MERGED', 'PROSPECTIVE')",
            name=op.f("ck_legal_entities_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legal_entities")),
        sa.UniqueConstraint("entity_key", name=op.f("uq_legal_entities_entity_key")),
    )
    op.create_index(
        "ix_legal_entities_status", "legal_entities", ["status", "is_in_scope"], unique=False
    )
    op.create_table(
        "license_types",
        sa.Column("license_type_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('COLLECTION_AGENCY', 'DEBT_COLLECTION', 'BUSINESS_LICENSE', 'CONSUMER_FINANCE', 'BRANCH', 'REGISTRATION', 'BOND', 'ANNUAL_REPORT', 'OTHER')",
            name=op.f("ck_license_types_category"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_license_types")),
        sa.UniqueConstraint("license_type_key", name=op.f("uq_license_types_license_type_key")),
    )
    op.create_table(
        "licensing_notifications",
        sa.Column("notification_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("recipient_actor", sa.Text(), nullable=False),
        sa.Column("escalation_level", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_licensing_notifications")),
        sa.UniqueConstraint("idempotency_key", name="uq_licensing_notifications_idem"),
    )
    op.create_index(
        "ix_licensing_notifications_entity",
        "licensing_notifications",
        ["entity_type", "entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_licensing_notifications_recipient",
        "licensing_notifications",
        ["recipient_actor", "read_at"],
        unique=False,
    )
    op.create_table(
        "requirement_rule_sets",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("approved_by_actor", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("derived_from_rule_set_id", sa.UUID(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name=op.f("ck_requirement_rule_sets_status")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_requirement_rule_sets_version")),
        sa.ForeignKeyConstraint(
            ["derived_from_rule_set_id"],
            ["requirement_rule_sets.id"],
            name=op.f("fk_requirement_rule_sets_derived_from_rule_set_id_requirement_rule_sets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requirement_rule_sets")),
        sa.UniqueConstraint("name", "version", name="uq_requirement_rule_sets_version"),
    )
    op.create_index(
        "uq_requirement_rule_sets_active",
        "requirement_rule_sets",
        ["name"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "deadline_rules",
        sa.Column("rule_key", sa.Text(), nullable=False),
        sa.Column("obligation_type", sa.Text(), nullable=False),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=True),
        sa.Column("license_type_id", sa.UUID(), nullable=True),
        sa.Column("recurrence_type", sa.Text(), nullable=False),
        sa.Column(
            "recurrence_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("adjustment_policy", sa.Text(), nullable=False),
        sa.Column(
            "escalation_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "milestone_offsets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "source_snapshot_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "adjustment_policy IN ('NONE', 'PREVIOUS_BUSINESS_DAY', 'NEXT_BUSINESS_DAY', 'JURISDICTION_SPECIFIC', 'MANUAL_REVIEW')",
            name=op.f("ck_deadline_rules_adjustment"),
        ),
        sa.CheckConstraint(
            "obligation_type IN ('LICENSE_RENEWAL', 'BOND_RENEWAL', 'ANNUAL_REPORT', 'FINANCIAL_DOCUMENT', 'CERTIFICATE_RENEWAL', 'INITIAL_APPLICATION', 'AMENDMENT', 'DEFICIENCY_RESPONSE', 'INFORMATION_RESPONSE', 'SURRENDER', 'OTHER')",
            name=op.f("ck_deadline_rules_obligation_type"),
        ),
        sa.CheckConstraint(
            "recurrence_type IN ('FIXED_ANNUAL_DATE', 'ISSUE_ANNIVERSARY', 'EXPIRATION_ANNIVERSARY', 'REGULATOR_SUPPLIED', 'NMLS_ANNUAL_RENEWAL_WINDOW', 'BOND_EXPIRATION', 'ANNUAL_REPORT_DATE', 'RELATIVE_TO_CASE_EVENT', 'CUSTOM_INTERVAL', 'MANUAL_DATE')",
            name=op.f("ck_deadline_rules_recurrence_type"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name=op.f("ck_deadline_rules_status")
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name=op.f("ck_deadline_rules_effective_range"),
        ),
        sa.CheckConstraint(
            "lead_time_days IS NULL OR lead_time_days >= 0",
            name=op.f("ck_deadline_rules_lead_time_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdictions.id"],
            name=op.f("fk_deadline_rules_jurisdiction_id_jurisdictions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["license_type_id"],
            ["license_types.id"],
            name=op.f("fk_deadline_rules_license_type_id_license_types"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deadline_rules")),
        sa.UniqueConstraint("rule_key", name=op.f("uq_deadline_rules_rule_key")),
    )
    op.create_index(
        "ix_deadline_rules_scope",
        "deadline_rules",
        ["obligation_type", "jurisdiction_id", "license_type_id"],
        unique=False,
    )
    op.create_index("ix_deadline_rules_status", "deadline_rules", ["status"], unique=False)
    op.create_table(
        "information_owner_assignments",
        sa.Column("information_definition_id", sa.UUID(), nullable=False),
        sa.Column("legal_entity_id", sa.UUID(), nullable=True),
        sa.Column("owner_actor", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("assigned_by_actor", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["information_definition_id"],
            ["information_definitions.id"],
            name=op.f(
                "fk_information_owner_assignments_information_definition_id_information_definitions"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["legal_entity_id"],
            ["legal_entities.id"],
            name=op.f("fk_information_owner_assignments_legal_entity_id_legal_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_information_owner_assignments")),
        sa.UniqueConstraint(
            "information_definition_id",
            "legal_entity_id",
            "owner_actor",
            name="uq_information_owner_assignments",
        ),
    )
    op.create_index(
        "ix_information_owner_assignments_owner",
        "information_owner_assignments",
        ["owner_actor", "is_active"],
        unique=False,
    )
    op.create_table(
        "operating_profiles",
        sa.Column("legal_entity_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "facts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("approved_by_actor", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name=op.f("ck_operating_profiles_status")
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name=op.f("ck_operating_profiles_effective_range"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_operating_profiles_version_positive")),
        sa.ForeignKeyConstraint(
            ["legal_entity_id"],
            ["legal_entities.id"],
            name=op.f("fk_operating_profiles_legal_entity_id_legal_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operating_profiles")),
        sa.UniqueConstraint(
            "legal_entity_id", "name", "version", name="uq_operating_profiles_version"
        ),
    )
    op.create_index(
        "uq_operating_profiles_active",
        "operating_profiles",
        ["legal_entity_id", "name"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "requirement_rules",
        sa.Column("rule_set_id", sa.UUID(), nullable=False),
        sa.Column("rule_key", sa.Text(), nullable=False),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=True),
        sa.Column("license_type_id", sa.UUID(), nullable=True),
        sa.Column(
            "conditions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("explanation_template", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column(
            "filing_channels",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "required_facts",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "requires_counsel_review", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("retired_by_actor", sa.Text(), nullable=True),
        sa.Column("retired_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('LIKELY_REQUIRED', 'POSSIBLY_REQUIRED', 'LIKELY_NOT_REQUIRED', 'COUNSEL_REVIEW', 'OUT_OF_SCOPE', 'INSUFFICIENT_INFORMATION')",
            name=op.f("ck_requirement_rules_outcome"),
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name=op.f("ck_requirement_rules_effective_range"),
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdictions.id"],
            name=op.f("fk_requirement_rules_jurisdiction_id_jurisdictions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["license_type_id"],
            ["license_types.id"],
            name=op.f("fk_requirement_rules_license_type_id_license_types"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_set_id"],
            ["requirement_rule_sets.id"],
            name=op.f("fk_requirement_rules_rule_set_id_requirement_rule_sets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requirement_rules")),
        sa.UniqueConstraint("rule_set_id", "rule_key", name="uq_requirement_rules_key"),
    )
    op.create_index(
        "ix_requirement_rules_enabled",
        "requirement_rules",
        ["rule_set_id", "enabled", "priority"],
        unique=False,
    )
    op.create_index(
        "ix_requirement_rules_scope",
        "requirement_rules",
        ["rule_set_id", "jurisdiction_id", "license_type_id"],
        unique=False,
    )
    op.create_table(
        "requirement_sources",
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("authority_level", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("official_url", sa.Text(), nullable=True),
        sa.Column("access_method", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_status", sa.Text(), nullable=False),
        sa.Column("current_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("owner_actor", sa.Text(), nullable=True),
        sa.Column("freshness_days", sa.Integer(), nullable=True),
        sa.Column("citation_label", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "access_method IN ('MANUAL_URL_REGISTRATION', 'PUBLIC_PAGE_FETCH', 'MANUAL_UPLOAD', 'NMLS_CHECKLIST_EXPORT', 'COUNSEL_DELIVERY', 'VENDOR_DELIVERY', 'INTERNAL_AUTHORING')",
            name=op.f("ck_requirement_sources_access"),
        ),
        sa.CheckConstraint(
            "authority_level IN ('OFFICIAL_PRIMARY', 'OFFICIAL_GUIDANCE', 'APPROVED_COUNSEL', 'VENDOR_OPERATIONAL', 'INTERNAL', 'UNVERIFIED')",
            name=op.f("ck_requirement_sources_authority"),
        ),
        sa.CheckConstraint(
            "source_type IN ('NMLS_CHECKLIST', 'NMLS_RENEWAL_CHECKLIST', 'REGULATOR_WEBPAGE', 'REGULATOR_PDF', 'STATUTE', 'REGULATION', 'REGULATOR_GUIDANCE', 'COUNSEL_MEMO', 'VENDOR_CHECKLIST', 'INTERNAL_POLICY', 'OTHER')",
            name=op.f("ck_requirement_sources_type"),
        ),
        sa.CheckConstraint(
            "verification_status IN ('UNVERIFIED', 'VERIFIED', 'STALE', 'CHANGED_PENDING_REVIEW', 'RETIRED')",
            name=op.f("ck_requirement_sources_verification"),
        ),
        sa.ForeignKeyConstraint(
            ["current_snapshot_id"],
            ["requirement_source_snapshots.id"],
            name="fk_requirement_sources_current_snapshot",
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdictions.id"],
            name=op.f("fk_requirement_sources_jurisdiction_id_jurisdictions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_requirement_sources_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requirement_sources")),
        sa.UniqueConstraint("source_key", name=op.f("uq_requirement_sources_source_key")),
    )
    op.create_index(
        "ix_requirement_sources_jurisdiction",
        "requirement_sources",
        ["jurisdiction_id", "source_type"],
        unique=False,
    )
    op.create_index(
        "ix_requirement_sources_verification",
        "requirement_sources",
        ["verification_status", "last_verified_at"],
        unique=False,
    )
    op.create_table(
        "requirement_assessments",
        sa.Column("assessment_key", sa.Text(), nullable=False),
        sa.Column("legal_entity_id", sa.UUID(), nullable=False),
        sa.Column("operating_profile_id", sa.UUID(), nullable=False),
        sa.Column("assessment_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "requested_jurisdictions",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column(
            "input_facts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("input_fingerprint", sa.Text(), nullable=False),
        sa.Column("rule_set_id", sa.UUID(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("created_by_actor", sa.Text(), nullable=False),
        sa.Column("reviewed_by_actor", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_assessment_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "assessment_type IN ('INITIAL_FOOTPRINT', 'EXPANSION', 'PERIODIC_REVIEW', 'ACTIVITY_CHANGE', 'SINGLE_JURISDICTION')",
            name=op.f("ck_requirement_assessments_type"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'EVALUATED', 'PENDING_REVIEW', 'APPROVED', 'COUNSEL_REVIEW', 'REJECTED', 'SUPERSEDED')",
            name=op.f("ck_requirement_assessments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["legal_entity_id"],
            ["legal_entities.id"],
            name=op.f("fk_requirement_assessments_legal_entity_id_legal_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["operating_profile_id"],
            ["operating_profiles.id"],
            name=op.f("fk_requirement_assessments_operating_profile_id_operating_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_set_id"],
            ["requirement_rule_sets.id"],
            name=op.f("fk_requirement_assessments_rule_set_id_requirement_rule_sets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_assessment_id"],
            ["requirement_assessments.id"],
            name=op.f(
                "fk_requirement_assessments_superseded_by_assessment_id_requirement_assessments"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requirement_assessments")),
        sa.UniqueConstraint(
            "assessment_key", name=op.f("uq_requirement_assessments_assessment_key")
        ),
    )
    op.create_index(
        "ix_requirement_assessments_entity",
        "requirement_assessments",
        ["legal_entity_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_requirement_assessments_fingerprint",
        "requirement_assessments",
        ["input_fingerprint"],
        unique=False,
    )
    op.create_table(
        "requirement_source_snapshots",
        sa.Column("requirement_source_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_storage_uri", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("extracted_text_storage_uri", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column(
            "change_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("previous_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("review_status", sa.Text(), nullable=False),
        sa.Column("reviewed_by_actor", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("affects_rules", sa.Boolean(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "review_status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED', 'SUPERSEDED')",
            name=op.f("ck_requirement_source_snapshots_review"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_requirement_source_snapshots_version")),
        sa.ForeignKeyConstraint(
            ["previous_snapshot_id"],
            ["requirement_source_snapshots.id"],
            name=op.f(
                "fk_requirement_source_snapshots_previous_snapshot_id_requirement_source_snapshots"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_source_id"],
            ["requirement_sources.id"],
            name=op.f("fk_requirement_source_snapshots_requirement_source_id_requirement_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requirement_source_snapshots")),
        sa.UniqueConstraint(
            "requirement_source_id", "version", name="uq_requirement_source_snapshots_version"
        ),
    )
    op.create_index(
        "ix_requirement_source_snapshots_hash",
        "requirement_source_snapshots",
        ["content_sha256"],
        unique=False,
    )
    op.create_index(
        "ix_requirement_source_snapshots_review",
        "requirement_source_snapshots",
        ["review_status", "retrieved_at"],
        unique=False,
    )
    # requirement_sources.current_snapshot_id and requirement_source_snapshots
    # .requirement_source_id reference each other, so this FK is added after both
    # tables exist (mirrors fk_documents_current_version in 0003).
    op.create_foreign_key(
        "fk_requirement_sources_current_snapshot",
        "requirement_sources",
        "requirement_source_snapshots",
        ["current_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "packet_templates",
        sa.Column("template_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=True),
        sa.Column("license_type_id", sa.UUID(), nullable=True),
        sa.Column("case_type", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("requirement_source_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "case_type IS NULL OR case_type IN ('LICENSE_RENEWAL', 'INITIAL_LICENSE', 'LICENSE_AMENDMENT', 'BOND_RENEWAL', 'BOND_RIDER', 'ANNUAL_REPORT', 'FINANCIAL_DOCUMENT', 'DEFICIENCY_RESPONSE', 'INFORMATION_RESPONSE', 'SURRENDER', 'OTHER')",
            name=op.f("ck_packet_templates_case_type"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name=op.f("ck_packet_templates_status")
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdictions.id"],
            name=op.f("fk_packet_templates_jurisdiction_id_jurisdictions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["license_type_id"],
            ["license_types.id"],
            name=op.f("fk_packet_templates_license_type_id_license_types"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_source_snapshot_id"],
            ["requirement_source_snapshots.id"],
            name=op.f(
                "fk_packet_templates_requirement_source_snapshot_id_requirement_source_snapshots"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_packet_templates")),
        sa.UniqueConstraint("template_key", name=op.f("uq_packet_templates_template_key")),
    )
    op.create_index(
        "ix_packet_templates_scope",
        "packet_templates",
        ["jurisdiction_id", "license_type_id", "case_type"],
        unique=False,
    )
    op.create_table(
        "requirement_assessment_results",
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=False),
        sa.Column("license_type_id", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column(
            "filing_channels",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "facts_used",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "missing_facts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "matched_rule_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column(
            "source_citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_freshness_status", sa.Text(), nullable=False),
        sa.Column(
            "conflicting_rule_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column(
            "requires_human_review", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "requires_counsel_review", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("reviewed_outcome", sa.Text(), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by_actor", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('LIKELY_REQUIRED', 'POSSIBLY_REQUIRED', 'LIKELY_NOT_REQUIRED', 'COUNSEL_REVIEW', 'OUT_OF_SCOPE', 'INSUFFICIENT_INFORMATION')",
            name=op.f("ck_requirement_assessment_results_ck_requirement_results_outcome"),
        ),
        sa.CheckConstraint(
            "source_freshness_status IN ('FRESH', 'DUE_FOR_VERIFICATION', 'STALE', 'UNKNOWN', 'NO_SOURCE')",
            name=op.f("ck_requirement_assessment_results_ck_requirement_results_freshness"),
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["requirement_assessments.id"],
            name=op.f("fk_requirement_assessment_results_assessment_id_requirement_assessments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdictions.id"],
            name=op.f("fk_requirement_assessment_results_jurisdiction_id_jurisdictions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["license_type_id"],
            ["license_types.id"],
            name=op.f("fk_requirement_assessment_results_license_type_id_license_types"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requirement_assessment_results")),
    )
    op.create_index(
        "ix_requirement_results_outcome",
        "requirement_assessment_results",
        ["assessment_id", "outcome"],
        unique=False,
    )
    op.create_index(
        "ix_requirement_results_review",
        "requirement_assessment_results",
        ["requires_human_review", "outcome"],
        unique=False,
    )
    op.create_index(
        "uq_requirement_assessment_results_scope",
        "requirement_assessment_results",
        [
            "assessment_id",
            "jurisdiction_id",
            sa.literal_column(
                "COALESCE(license_type_id, '00000000-0000-0000-0000-000000000000'::uuid)"
            ),
        ],
        unique=True,
    )
    op.create_table(
        "requirement_rule_sources",
        sa.Column("requirement_rule_id", sa.UUID(), nullable=False),
        sa.Column("requirement_source_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("citation_detail", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["requirement_rule_id"],
            ["requirement_rules.id"],
            name=op.f("fk_requirement_rule_sources_requirement_rule_id_requirement_rules"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_source_snapshot_id"],
            ["requirement_source_snapshots.id"],
            name=op.f(
                "fk_requirement_rule_sources_requirement_source_snapshot_id_requirement_source_snapshots"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requirement_rule_sources")),
        sa.UniqueConstraint(
            "requirement_rule_id",
            "requirement_source_snapshot_id",
            name="uq_requirement_rule_sources_pair",
        ),
    )
    op.create_index(
        "ix_requirement_rule_sources_snapshot",
        "requirement_rule_sources",
        ["requirement_source_snapshot_id"],
        unique=False,
    )
    op.create_table(
        "assessment_overrides",
        sa.Column("assessment_result_id", sa.UUID(), nullable=False),
        sa.Column("original_outcome", sa.Text(), nullable=False),
        sa.Column("overridden_outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False),
        sa.Column("approved_by_actor", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_actor", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "authority IN ('COMPLIANCE_MANAGER', 'INTERNAL_COUNSEL', 'EXTERNAL_COUNSEL', 'REGULATOR_WRITTEN_GUIDANCE', 'EXECUTIVE')",
            name=op.f("ck_assessment_overrides_authority"),
        ),
        sa.CheckConstraint(
            "original_outcome IN ('LIKELY_REQUIRED', 'POSSIBLY_REQUIRED', 'LIKELY_NOT_REQUIRED', 'COUNSEL_REVIEW', 'OUT_OF_SCOPE', 'INSUFFICIENT_INFORMATION')",
            name=op.f("ck_assessment_overrides_original"),
        ),
        sa.CheckConstraint(
            "overridden_outcome IN ('LIKELY_REQUIRED', 'POSSIBLY_REQUIRED', 'LIKELY_NOT_REQUIRED', 'COUNSEL_REVIEW', 'OUT_OF_SCOPE', 'INSUFFICIENT_INFORMATION')",
            name=op.f("ck_assessment_overrides_overridden"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name=op.f("ck_assessment_overrides_validity_range"),
        ),
        sa.ForeignKeyConstraint(
            ["assessment_result_id"],
            ["requirement_assessment_results.id"],
            name=op.f(
                "fk_assessment_overrides_assessment_result_id_requirement_assessment_results"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_overrides")),
    )
    op.create_index(
        "ix_assessment_overrides_result",
        "assessment_overrides",
        ["assessment_result_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "packet_template_items",
        sa.Column("packet_template_id", sa.UUID(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "selection_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["packet_template_id"],
            ["packet_templates.id"],
            name=op.f("fk_packet_template_items_packet_template_id_packet_templates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_packet_template_items")),
        sa.UniqueConstraint("packet_template_id", "item_key", name="uq_packet_template_items_key"),
    )
    op.create_index(
        "ix_packet_template_items_template",
        "packet_template_items",
        ["packet_template_id", "sort_order"],
        unique=False,
    )
    op.create_table(
        "form_templates",
        sa.Column("template_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("form_family", sa.Text(), nullable=False),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=True),
        sa.Column("license_type_id", sa.UUID(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("template_document_id", sa.UUID(), nullable=False),
        sa.Column("form_format", sa.Text(), nullable=False),
        sa.Column("field_detection_status", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("detected_field_count", sa.Integer(), nullable=True),
        sa.Column("template_sha256", sa.Text(), nullable=True),
        sa.Column("inspection_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by_actor", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_template_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "field_detection_status IN ('NOT_INSPECTED', 'INSPECTED', 'NO_FIELDS_FOUND', 'MANUAL_MAPPING_REQUIRED', 'INSPECTION_FAILED')",
            name=op.f("ck_form_templates_detection"),
        ),
        sa.CheckConstraint(
            "form_family IN ('NMLS_MU1', 'NMLS_MU2', 'NMLS_MU3', 'STATE_APPLICATION', 'STATE_RENEWAL', 'BOND_FORM', 'ANNUAL_REPORT', 'VENDOR_FORM', 'INTERNAL_WORKSHEET', 'OTHER')",
            name=op.f("ck_form_templates_family"),
        ),
        sa.CheckConstraint(
            "form_format IN ('PDF_ACROFORM', 'FLAT_PDF', 'DOCX', 'XLSX', 'WEB_WORKSHEET', 'UNKNOWN')",
            name=op.f("ck_form_templates_format"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PENDING_REVIEW', 'ACTIVE', 'RETIRED')",
            name=op.f("ck_form_templates_status"),
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name=op.f("ck_form_templates_effective_range"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_form_templates_version")),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdictions.id"],
            name=op.f("fk_form_templates_jurisdiction_id_jurisdictions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["license_type_id"],
            ["license_types.id"],
            name=op.f("fk_form_templates_license_type_id_license_types"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_template_id"],
            ["form_templates.id"],
            name=op.f("fk_form_templates_supersedes_template_id_form_templates"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["template_document_id"],
            ["documents.id"],
            name=op.f("fk_form_templates_template_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_templates")),
        sa.UniqueConstraint("template_key", name="uq_form_templates_key"),
    )
    op.create_index(
        "ix_form_templates_family", "form_templates", ["form_family", "status"], unique=False
    )
    op.create_index(
        "ix_form_templates_scope",
        "form_templates",
        ["jurisdiction_id", "license_type_id"],
        unique=False,
    )
    op.create_table(
        "license_inventory",
        sa.Column("license_key", sa.Text(), nullable=False),
        sa.Column("legal_entity_id", sa.UUID(), nullable=False),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=False),
        sa.Column("license_type_id", sa.UUID(), nullable=False),
        sa.Column("regulator_organization_id", sa.UUID(), nullable=True),
        sa.Column("vendor_organization_id", sa.UUID(), nullable=True),
        sa.Column("license_number", sa.Text(), nullable=True),
        sa.Column("nmls_license_id", sa.Text(), nullable=True),
        sa.Column("filing_channel", sa.Text(), nullable=False),
        sa.Column("current_status", sa.Text(), nullable=False),
        sa.Column(
            "represents_additional_authority",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("authority_label", sa.Text(), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column("renewal_due_date", sa.Date(), nullable=True),
        sa.Column("internal_start_date", sa.Date(), nullable=True),
        sa.Column("surrender_date", sa.Date(), nullable=True),
        sa.Column("next_review_date", sa.Date(), nullable=True),
        sa.Column("responsible_owner", sa.Text(), nullable=True),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_confidence", sa.Text(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "current_status IN ('NOT_STARTED', 'APPLICATION_IN_PROGRESS', 'PENDING_REGULATOR', 'APPROVED', 'ACTIVE', 'RENEWAL_IN_PROGRESS', 'EXPIRED', 'REINSTATING', 'SUSPENDED', 'REVOKED', 'SURRENDERED', 'NOT_REQUIRED', 'UNKNOWN')",
            name=op.f("ck_license_inventory_status"),
        ),
        sa.CheckConstraint(
            "filing_channel IN ('NMLS', 'STATE_PORTAL', 'LOCAL_PORTAL', 'PAPER', 'EMAIL', 'VENDOR_MANAGED', 'MULTIPLE_CHANNELS', 'UNKNOWN')",
            name=op.f("ck_license_inventory_filing_channel"),
        ),
        sa.CheckConstraint(
            "source_confidence IN ('VERIFIED_DOCUMENT', 'REGULATOR_CONFIRMED', 'VENDOR_REPORTED', 'TRACKER_IMPORT', 'MANUAL_ENTRY', 'UNVERIFIED')",
            name=op.f("ck_license_inventory_confidence"),
        ),
        sa.CheckConstraint(
            "expiration_date IS NULL OR issue_date IS NULL OR expiration_date >= issue_date",
            name=op.f("ck_license_inventory_date_sequence"),
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdictions.id"],
            name=op.f("fk_license_inventory_jurisdiction_id_jurisdictions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["legal_entity_id"],
            ["legal_entities.id"],
            name=op.f("fk_license_inventory_legal_entity_id_legal_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["license_type_id"],
            ["license_types.id"],
            name=op.f("fk_license_inventory_license_type_id_license_types"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["regulator_organization_id"],
            ["organizations.id"],
            name=op.f("fk_license_inventory_regulator_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["documents.id"],
            name=op.f("fk_license_inventory_source_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_organization_id"],
            ["organizations.id"],
            name=op.f("fk_license_inventory_vendor_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_license_inventory")),
        sa.UniqueConstraint("license_key", name=op.f("uq_license_inventory_license_key")),
    )
    op.create_index(
        "ix_license_inventory_entity",
        "license_inventory",
        ["legal_entity_id", "current_status"],
        unique=False,
    )
    op.create_index(
        "ix_license_inventory_expiration", "license_inventory", ["expiration_date"], unique=False
    )
    op.create_index(
        "ix_license_inventory_jurisdiction",
        "license_inventory",
        ["jurisdiction_id", "license_type_id"],
        unique=False,
    )
    op.create_index(
        "ix_license_inventory_renewal_due", "license_inventory", ["renewal_due_date"], unique=False
    )
    op.create_index(
        "uq_license_inventory_live_authority",
        "license_inventory",
        ["legal_entity_id", "jurisdiction_id", "license_type_id"],
        unique=True,
        postgresql_where=sa.text(
            "represents_additional_authority = false AND current_status IN ('APPLICATION_IN_PROGRESS', 'PENDING_REGULATOR', 'APPROVED', 'ACTIVE', 'RENEWAL_IN_PROGRESS', 'REINSTATING', 'SUSPENDED')"
        ),
    )
    op.create_table(
        "tracker_import_runs",
        sa.Column("source_filename", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "mapping_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("dry_run", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("inserted_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("conflict_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("report_storage_uri", sa.Text(), nullable=True),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("plan_run_id", sa.UUID(), nullable=True),
        sa.Column("sheet_name", sa.Text(), nullable=True),
        sa.Column(
            "detected_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("initiated_by_actor", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PLANNING', 'PLANNED', 'APPLYING', 'COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED', 'CANCELLED')",
            name=op.f("ck_tracker_import_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["plan_run_id"],
            ["tracker_import_runs.id"],
            name=op.f("fk_tracker_import_runs_plan_run_id_tracker_import_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["documents.id"],
            name=op.f("fk_tracker_import_runs_source_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tracker_import_runs")),
    )
    op.create_index(
        "ix_tracker_import_runs_hash", "tracker_import_runs", ["source_sha256"], unique=False
    )
    op.create_index(
        "ix_tracker_import_runs_status",
        "tracker_import_runs",
        ["status", "started_at"],
        unique=False,
    )
    op.create_table(
        "form_template_fields",
        sa.Column("form_template_id", sa.UUID(), nullable=False),
        sa.Column("field_key", sa.Text(), nullable=False),
        sa.Column("native_field_name", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("field_type", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("allowed_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("sensitivity", sa.Text(), nullable=False),
        sa.Column("max_length", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "field_type IN ('TEXT', 'MULTILINE_TEXT', 'NUMBER', 'CURRENCY', 'DATE', 'CHECKBOX', 'RADIO', 'CHOICE', 'SIGNATURE', 'INITIALS', 'ATTESTATION', 'COMPUTED', 'UNKNOWN')",
            name=op.f("ck_form_template_fields_type"),
        ),
        sa.CheckConstraint(
            "sensitivity IN ('INTERNAL', 'CONFIDENTIAL', 'RESTRICTED', 'HIGHLY_RESTRICTED')",
            name=op.f("ck_form_template_fields_sensitivity"),
        ),
        sa.ForeignKeyConstraint(
            ["form_template_id"],
            ["form_templates.id"],
            name=op.f("fk_form_template_fields_form_template_id_form_templates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_template_fields")),
        sa.UniqueConstraint("form_template_id", "field_key", name="uq_form_template_fields_key"),
    )
    op.create_index(
        "ix_form_template_fields_template",
        "form_template_fields",
        ["form_template_id", "sort_order"],
        unique=False,
    )
    op.create_table(
        "license_bonds",
        sa.Column("bond_key", sa.Text(), nullable=False),
        sa.Column("legal_entity_id", sa.UUID(), nullable=False),
        sa.Column("license_id", sa.UUID(), nullable=True),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=True),
        sa.Column("bond_provider_organization_id", sa.UUID(), nullable=True),
        sa.Column("bond_number", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("currency", sa.Text(), server_default=sa.text("'USD'"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("bond_channel", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column("continuous", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cancellation_notice_date", sa.Date(), nullable=True),
        sa.Column("bond_form_document_id", sa.UUID(), nullable=True),
        sa.Column("rider_document_id", sa.UUID(), nullable=True),
        sa.Column("continuation_document_id", sa.UUID(), nullable=True),
        sa.Column("responsible_owner", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "bond_channel IN ('NMLS_ESB', 'PAPER_ORIGINAL', 'VENDOR_MANAGED', 'STATE_SPECIFIC', 'UNKNOWN')",
            name=op.f("ck_license_bonds_channel"),
        ),
        sa.CheckConstraint(
            "status IN ('NOT_REQUIRED', 'PENDING', 'ACTIVE', 'CONTINUED', 'RIDER_PENDING', 'EXPIRED', 'CANCELLED', 'UNKNOWN')",
            name=op.f("ck_license_bonds_status"),
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount >= 0", name=op.f("ck_license_bonds_amount_non_negative")
        ),
        sa.CheckConstraint(
            "expiration_date IS NULL OR effective_date IS NULL OR expiration_date >= effective_date",
            name=op.f("ck_license_bonds_date_sequence"),
        ),
        sa.ForeignKeyConstraint(
            ["bond_form_document_id"],
            ["documents.id"],
            name=op.f("fk_license_bonds_bond_form_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["bond_provider_organization_id"],
            ["organizations.id"],
            name=op.f("fk_license_bonds_bond_provider_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["continuation_document_id"],
            ["documents.id"],
            name=op.f("fk_license_bonds_continuation_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdictions.id"],
            name=op.f("fk_license_bonds_jurisdiction_id_jurisdictions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["legal_entity_id"],
            ["legal_entities.id"],
            name=op.f("fk_license_bonds_legal_entity_id_legal_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["license_id"],
            ["license_inventory.id"],
            name=op.f("fk_license_bonds_license_id_license_inventory"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rider_document_id"],
            ["documents.id"],
            name=op.f("fk_license_bonds_rider_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_license_bonds")),
        sa.UniqueConstraint("bond_key", name=op.f("uq_license_bonds_bond_key")),
    )
    op.create_index(
        "ix_license_bonds_expiration", "license_bonds", ["expiration_date"], unique=False
    )
    op.create_index(
        "ix_license_bonds_license", "license_bonds", ["license_id", "status"], unique=False
    )
    op.create_table(
        "license_status_events",
        sa.Column("license_id", sa.UUID(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("source_type", sa.Text(), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "to_status IN ('NOT_STARTED', 'APPLICATION_IN_PROGRESS', 'PENDING_REGULATOR', 'APPROVED', 'ACTIVE', 'RENEWAL_IN_PROGRESS', 'EXPIRED', 'REINSTATING', 'SUSPENDED', 'REVOKED', 'SURRENDERED', 'NOT_REQUIRED', 'UNKNOWN')",
            name=op.f("ck_license_status_events_to_status"),
        ),
        sa.ForeignKeyConstraint(
            ["license_id"],
            ["license_inventory.id"],
            name=op.f("fk_license_status_events_license_id_license_inventory"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_license_status_events")),
    )
    op.create_index(
        "ix_license_status_events_license",
        "license_status_events",
        ["license_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "tracker_import_rows",
        sa.Column("import_run_id", sa.UUID(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("row_fingerprint", sa.Text(), nullable=False),
        sa.Column(
            "source_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("normalized_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("target_record_id", sa.UUID(), nullable=True),
        sa.Column("error_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IS NULL OR action IN ('INSERT', 'UPDATE', 'SKIP_UNCHANGED', 'SKIP_DUPLICATE', 'SKIP_NEWER_TARGET', 'CONFLICT_REVIEW', 'ERROR')",
            name=op.f("ck_tracker_import_rows_action"),
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["tracker_import_runs.id"],
            name=op.f("fk_tracker_import_rows_import_run_id_tracker_import_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tracker_import_rows")),
        sa.UniqueConstraint("import_run_id", "row_number", name="uq_tracker_import_rows_number"),
    )
    op.create_index(
        "ix_tracker_import_rows_fingerprint",
        "tracker_import_rows",
        ["row_fingerprint"],
        unique=False,
    )
    op.create_index(
        "ix_tracker_import_rows_run",
        "tracker_import_rows",
        ["import_run_id", "action"],
        unique=False,
    )
    op.create_index(
        "ix_tracker_import_rows_target", "tracker_import_rows", ["target_record_id"], unique=False
    )
    op.create_table(
        "compliance_obligations",
        sa.Column("obligation_key", sa.Text(), nullable=False),
        sa.Column("legal_entity_id", sa.UUID(), nullable=False),
        sa.Column("license_id", sa.UUID(), nullable=True),
        sa.Column("bond_id", sa.UUID(), nullable=True),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=True),
        sa.Column("obligation_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("recurrence_rule", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("statutory_due_date", sa.Date(), nullable=True),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column("internal_start_date", sa.Date(), nullable=True),
        sa.Column("responsible_owner", sa.Text(), nullable=True),
        sa.Column("vendor_organization_id", sa.UUID(), nullable=True),
        sa.Column("regulator_organization_id", sa.UUID(), nullable=True),
        sa.Column(
            "requirement_source_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("predecessor_obligation_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "obligation_type IN ('LICENSE_RENEWAL', 'BOND_RENEWAL', 'ANNUAL_REPORT', 'FINANCIAL_DOCUMENT', 'CERTIFICATE_RENEWAL', 'INITIAL_APPLICATION', 'AMENDMENT', 'DEFICIENCY_RESPONSE', 'INFORMATION_RESPONSE', 'SURRENDER', 'OTHER')",
            name=op.f("ck_compliance_obligations_type"),
        ),
        sa.CheckConstraint(
            "status IN ('PLANNED', 'ACTIVE', 'IN_CASE', 'SATISFIED', 'WAIVED', 'NOT_APPLICABLE', 'SUPERSEDED', 'CANCELLED')",
            name=op.f("ck_compliance_obligations_status"),
        ),
        sa.ForeignKeyConstraint(
            ["bond_id"],
            ["license_bonds.id"],
            name=op.f("fk_compliance_obligations_bond_id_license_bonds"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdictions.id"],
            name=op.f("fk_compliance_obligations_jurisdiction_id_jurisdictions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["legal_entity_id"],
            ["legal_entities.id"],
            name=op.f("fk_compliance_obligations_legal_entity_id_legal_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["license_id"],
            ["license_inventory.id"],
            name=op.f("fk_compliance_obligations_license_id_license_inventory"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_obligation_id"],
            ["compliance_obligations.id"],
            name=op.f("fk_compliance_obligations_predecessor_obligation_id_compliance_obligations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["regulator_organization_id"],
            ["organizations.id"],
            name=op.f("fk_compliance_obligations_regulator_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_organization_id"],
            ["organizations.id"],
            name=op.f("fk_compliance_obligations_vendor_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compliance_obligations")),
        sa.UniqueConstraint(
            "obligation_key", name=op.f("uq_compliance_obligations_obligation_key")
        ),
    )
    op.create_index(
        "ix_compliance_obligations_due",
        "compliance_obligations",
        ["next_due_date", "status"],
        unique=False,
    )
    op.create_index(
        "ix_compliance_obligations_entity",
        "compliance_obligations",
        ["legal_entity_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_compliance_obligations_license", "compliance_obligations", ["license_id"], unique=False
    )
    op.create_index(
        "ix_compliance_obligations_type",
        "compliance_obligations",
        ["obligation_type", "status"],
        unique=False,
    )
    op.create_table(
        "form_field_mappings",
        sa.Column("form_template_field_id", sa.UUID(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("transformation", sa.Text(), nullable=True),
        sa.Column("mapping_status", sa.Text(), nullable=False),
        sa.Column("requires_review", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("default_value", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("approved_by_actor", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mapping_status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'RETIRED')",
            name=op.f("ck_form_field_mappings_status"),
        ),
        sa.CheckConstraint(
            "source_type IN ('INFORMATION_REGISTRY', 'LEGAL_ENTITY', 'LICENSE_INVENTORY', 'COMPLIANCE_CASE', 'DOCUMENT_METADATA', 'MANUAL_INPUT', 'SIGNATURE_REQUIRED', 'CALCULATED')",
            name=op.f("ck_form_field_mappings_source_type"),
        ),
        sa.ForeignKeyConstraint(
            ["form_template_field_id"],
            ["form_template_fields.id"],
            name=op.f("fk_form_field_mappings_form_template_field_id_form_template_fields"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_field_mappings")),
    )
    op.create_index(
        "ix_form_field_mappings_field",
        "form_field_mappings",
        ["form_template_field_id", "mapping_status"],
        unique=False,
    )
    op.create_index(
        "ix_form_field_mappings_source",
        "form_field_mappings",
        ["source_type", "source_key"],
        unique=False,
    )
    op.create_index(
        "uq_form_field_mappings_active",
        "form_field_mappings",
        ["form_template_field_id"],
        unique=True,
        postgresql_where=sa.text("mapping_status = 'APPROVED'"),
    )
    op.create_table(
        "compliance_cases",
        sa.Column("case_key", sa.Text(), nullable=False),
        sa.Column("obligation_id", sa.UUID(), nullable=False),
        sa.Column("legal_entity_id", sa.UUID(), nullable=False),
        sa.Column("license_id", sa.UUID(), nullable=True),
        sa.Column("bond_id", sa.UUID(), nullable=True),
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("case_type", sa.Text(), nullable=False),
        sa.Column("current_stage", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("statutory_due_date", sa.Date(), nullable=True),
        sa.Column("internal_target_date", sa.Date(), nullable=True),
        sa.Column("assigned_owner", sa.Text(), nullable=True),
        sa.Column("vendor_organization_id", sa.UUID(), nullable=True),
        sa.Column("regulator_organization_id", sa.UUID(), nullable=True),
        sa.Column("primary_conversation_id", sa.Text(), nullable=True),
        sa.Column("close_reason", sa.Text(), nullable=True),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("created_by_actor", sa.Text(), nullable=True),
        sa.Column("stage_entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "case_type IN ('LICENSE_RENEWAL', 'INITIAL_LICENSE', 'LICENSE_AMENDMENT', 'BOND_RENEWAL', 'BOND_RIDER', 'ANNUAL_REPORT', 'FINANCIAL_DOCUMENT', 'DEFICIENCY_RESPONSE', 'INFORMATION_RESPONSE', 'SURRENDER', 'OTHER')",
            name=op.f("ck_compliance_cases_type"),
        ),
        sa.CheckConstraint(
            "current_stage IN ('DUE_IDENTIFIED', 'CASE_PLANNING', 'VENDOR_OUTREACH_PENDING', 'VENDOR_OUTREACH_SENT', 'VENDOR_QUESTIONS', 'INTERNAL_INFORMATION_PENDING', 'ANSWERS_READY', 'ANSWERS_SENT', 'DOCUMENT_CHECKLIST_RECEIVED', 'DOCUMENTS_PENDING', 'PACKET_BUILDING', 'PACKET_READY_FOR_REVIEW', 'PACKET_APPROVED', 'PACKET_SENT', 'FORM_RECEIVED', 'FORM_PREPARATION', 'FORM_MISSING_INFORMATION', 'FORM_READY_FOR_REVIEW', 'SIGNATURE_PENDING', 'SIGNED_FORM_RECEIVED', 'SUBMISSION_PENDING', 'SUBMITTED_TO_VENDOR', 'SUBMITTED_TO_REGULATOR', 'VENDOR_VALIDATION', 'REGULATOR_REVIEW', 'DEFICIENCY_RECEIVED', 'RENEWED_EVIDENCE_RECEIVED', 'INVENTORY_UPDATE_PENDING', 'COMPLETED', 'BLOCKED', 'CANCELLED')",
            name=op.f("ck_compliance_cases_stage"),
        ),
        sa.CheckConstraint(
            "priority IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')",
            name=op.f("ck_compliance_cases_priority"),
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'IN_PROGRESS', 'WAITING_INTERNAL', 'WAITING_VENDOR', 'WAITING_SIGNATURE', 'WAITING_SUBMISSION', 'WAITING_REGULATOR', 'BLOCKED', 'COMPLETED', 'CANCELLED', 'OVERDUE')",
            name=op.f("ck_compliance_cases_status"),
        ),
        sa.ForeignKeyConstraint(
            ["bond_id"],
            ["license_bonds.id"],
            name=op.f("fk_compliance_cases_bond_id_license_bonds"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["legal_entity_id"],
            ["legal_entities.id"],
            name=op.f("fk_compliance_cases_legal_entity_id_legal_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["license_id"],
            ["license_inventory.id"],
            name=op.f("fk_compliance_cases_license_id_license_inventory"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["obligation_id"],
            ["compliance_obligations.id"],
            name=op.f("fk_compliance_cases_obligation_id_compliance_obligations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["regulator_organization_id"],
            ["organizations.id"],
            name=op.f("fk_compliance_cases_regulator_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["licensing_tasks.id"],
            name=op.f("fk_compliance_cases_task_id_licensing_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_organization_id"],
            ["organizations.id"],
            name=op.f("fk_compliance_cases_vendor_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compliance_cases")),
        sa.UniqueConstraint("case_key", name=op.f("uq_compliance_cases_case_key")),
    )
    op.create_index(
        "ix_compliance_cases_entity",
        "compliance_cases",
        ["legal_entity_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_compliance_cases_obligation", "compliance_cases", ["obligation_id"], unique=False
    )
    op.create_index(
        "ix_compliance_cases_owner", "compliance_cases", ["assigned_owner", "status"], unique=False
    )
    op.create_index(
        "ix_compliance_cases_stage", "compliance_cases", ["current_stage", "status"], unique=False
    )
    op.create_index(
        "ix_compliance_cases_target", "compliance_cases", ["internal_target_date"], unique=False
    )
    op.create_table(
        "compliance_case_stage_events",
        sa.Column("compliance_case_id", sa.UUID(), nullable=False),
        sa.Column("from_stage", sa.Text(), nullable=True),
        sa.Column("to_stage", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("seconds_in_previous_stage", sa.BigInteger(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "to_stage IN ('DUE_IDENTIFIED', 'CASE_PLANNING', 'VENDOR_OUTREACH_PENDING', 'VENDOR_OUTREACH_SENT', 'VENDOR_QUESTIONS', 'INTERNAL_INFORMATION_PENDING', 'ANSWERS_READY', 'ANSWERS_SENT', 'DOCUMENT_CHECKLIST_RECEIVED', 'DOCUMENTS_PENDING', 'PACKET_BUILDING', 'PACKET_READY_FOR_REVIEW', 'PACKET_APPROVED', 'PACKET_SENT', 'FORM_RECEIVED', 'FORM_PREPARATION', 'FORM_MISSING_INFORMATION', 'FORM_READY_FOR_REVIEW', 'SIGNATURE_PENDING', 'SIGNED_FORM_RECEIVED', 'SUBMISSION_PENDING', 'SUBMITTED_TO_VENDOR', 'SUBMITTED_TO_REGULATOR', 'VENDOR_VALIDATION', 'REGULATOR_REVIEW', 'DEFICIENCY_RECEIVED', 'RENEWED_EVIDENCE_RECEIVED', 'INVENTORY_UPDATE_PENDING', 'COMPLETED', 'BLOCKED', 'CANCELLED')",
            name=op.f("ck_compliance_case_stage_events_ck_case_stage_events_to_stage"),
        ),
        sa.ForeignKeyConstraint(
            ["compliance_case_id"],
            ["compliance_cases.id"],
            name=op.f("fk_compliance_case_stage_events_compliance_case_id_compliance_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compliance_case_stage_events")),
    )
    op.create_index(
        "ix_case_stage_events_case",
        "compliance_case_stage_events",
        ["compliance_case_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "compliance_deadlines",
        sa.Column("obligation_id", sa.UUID(), nullable=False),
        sa.Column("compliance_case_id", sa.UUID(), nullable=True),
        sa.Column("deadline_type", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("internal_target_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("assigned_owner", sa.Text(), nullable=True),
        sa.Column("backup_owner", sa.Text(), nullable=True),
        sa.Column("source_rule_id", sa.UUID(), nullable=True),
        sa.Column(
            "manually_overridden", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("materialization_key", sa.Text(), nullable=True),
        sa.Column("last_escalation_level", sa.Text(), nullable=True),
        sa.Column("last_escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_adjustment", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_actor", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "deadline_type IN ('INTERNAL_START', 'VENDOR_OUTREACH', 'INFORMATION_DUE', 'DOCUMENT_PACKET_DUE', 'FORM_COMPLETION_DUE', 'SIGNATURE_DUE', 'SUBMISSION_DUE', 'STATUTORY_DUE', 'BOND_EXPIRY', 'ANNUAL_REPORT_DUE', 'DOCUMENT_EXPIRY', 'FOLLOW_UP')",
            name=op.f("ck_compliance_deadlines_type"),
        ),
        sa.CheckConstraint(
            "severity IN ('INFORMATIONAL', 'NORMAL', 'IMPORTANT', 'CRITICAL', 'REGULATORY_RISK')",
            name=op.f("ck_compliance_deadlines_severity"),
        ),
        sa.CheckConstraint(
            "status IN ('SCHEDULED', 'APPROACHING', 'DUE_TODAY', 'OVERDUE', 'COMPLETED', 'WAIVED', 'SUPERSEDED', 'CANCELLED')",
            name=op.f("ck_compliance_deadlines_status"),
        ),
        sa.ForeignKeyConstraint(
            ["compliance_case_id"],
            ["compliance_cases.id"],
            name=op.f("fk_compliance_deadlines_compliance_case_id_compliance_cases"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["obligation_id"],
            ["compliance_obligations.id"],
            name=op.f("fk_compliance_deadlines_obligation_id_compliance_obligations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_rule_id"],
            ["deadline_rules.id"],
            name=op.f("fk_compliance_deadlines_source_rule_id_deadline_rules"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compliance_deadlines")),
    )
    op.create_index(
        "ix_compliance_deadlines_case", "compliance_deadlines", ["compliance_case_id"], unique=False
    )
    op.create_index(
        "ix_compliance_deadlines_due", "compliance_deadlines", ["due_at", "status"], unique=False
    )
    op.create_index(
        "ix_compliance_deadlines_obligation",
        "compliance_deadlines",
        ["obligation_id", "deadline_type"],
        unique=False,
    )
    op.create_index(
        "ix_compliance_deadlines_owner",
        "compliance_deadlines",
        ["assigned_owner", "status"],
        unique=False,
    )
    op.create_index(
        "uq_compliance_deadlines_materialization",
        "compliance_deadlines",
        ["materialization_key"],
        unique=True,
        postgresql_where=sa.text("materialization_key IS NOT NULL"),
    )
    op.create_table(
        "document_packets",
        sa.Column("packet_key", sa.Text(), nullable=False),
        sa.Column("compliance_case_id", sa.UUID(), nullable=False),
        sa.Column("packet_template_id", sa.UUID(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.Text(), nullable=True),
        sa.Column(
            "manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("archive_storage_uri", sa.Text(), nullable=True),
        sa.Column("archive_sha256", sa.Text(), nullable=True),
        sa.Column("archive_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("cover_sheet_storage_uri", sa.Text(), nullable=True),
        sa.Column(
            "missing_items",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "validation_results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by_actor", sa.Text(), nullable=True),
        sa.Column("reviewed_by_actor", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_packet_id", sa.UUID(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'MISSING_ITEMS', 'READY_FOR_REVIEW', 'APPROVED', 'SUPERSEDED', 'REJECTED')",
            name=op.f("ck_document_packets_status"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_document_packets_version")),
        sa.ForeignKeyConstraint(
            ["compliance_case_id"],
            ["compliance_cases.id"],
            name=op.f("fk_document_packets_compliance_case_id_compliance_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["packet_template_id"],
            ["packet_templates.id"],
            name=op.f("fk_document_packets_packet_template_id_packet_templates"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_packet_id"],
            ["document_packets.id"],
            name=op.f("fk_document_packets_superseded_by_packet_id_document_packets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_packets")),
        sa.UniqueConstraint("compliance_case_id", "version", name="uq_document_packets_version"),
        sa.UniqueConstraint("packet_key", name=op.f("uq_document_packets_packet_key")),
    )
    op.create_index(
        "ix_document_packets_case",
        "document_packets",
        ["compliance_case_id", "status"],
        unique=False,
    )
    op.create_table(
        "form_instances",
        sa.Column("instance_key", sa.Text(), nullable=False),
        sa.Column("compliance_case_id", sa.UUID(), nullable=False),
        sa.Column("form_template_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("generated_document_id", sa.UUID(), nullable=True),
        sa.Column("worksheet_document_id", sa.UUID(), nullable=True),
        sa.Column("field_snapshot_sha256", sa.Text(), nullable=True),
        sa.Column("approved_draft_sha256", sa.Text(), nullable=True),
        sa.Column(
            "missing_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "validation_results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("prepared_by_actor", sa.Text(), nullable=True),
        sa.Column("reviewed_by_actor", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "signature_required", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "signature_status", sa.Text(), server_default=sa.text("'NOT_REQUIRED'"), nullable=False
        ),
        sa.Column("required_signatory_actor", sa.Text(), nullable=True),
        sa.Column("required_signatory_title", sa.Text(), nullable=True),
        sa.Column("signed_document_id", sa.UUID(), nullable=True),
        sa.Column("signed_recorded_by_actor", sa.Text(), nullable=True),
        sa.Column("signed_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_submission_reference", sa.Text(), nullable=True),
        sa.Column("external_submission_recorded_by_actor", sa.Text(), nullable=True),
        sa.Column("external_submission_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("superseded_by_instance_id", sa.UUID(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "signature_status IN ('NOT_REQUIRED', 'IDENTIFIED', 'APPROVED_FOR_SIGNATURE', 'SENT_FOR_SIGNATURE_EXTERNALLY', 'SIGNED_EVIDENCE_RECORDED', 'CANCELLED')",
            name=op.f("ck_form_instances_signature_status"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PREFILLED', 'MISSING_INFORMATION', 'READY_FOR_REVIEW', 'APPROVED_FOR_SIGNATURE', 'SIGNATURE_PENDING', 'SIGNED', 'READY_FOR_SUBMISSION', 'SUBMITTED_EXTERNALLY', 'SUPERSEDED', 'REJECTED')",
            name=op.f("ck_form_instances_status"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_form_instances_version")),
        sa.ForeignKeyConstraint(
            ["compliance_case_id"],
            ["compliance_cases.id"],
            name=op.f("fk_form_instances_compliance_case_id_compliance_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["form_template_id"],
            ["form_templates.id"],
            name=op.f("fk_form_instances_form_template_id_form_templates"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["generated_document_id"],
            ["documents.id"],
            name=op.f("fk_form_instances_generated_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["signed_document_id"],
            ["documents.id"],
            name=op.f("fk_form_instances_signed_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_instance_id"],
            ["form_instances.id"],
            name=op.f("fk_form_instances_superseded_by_instance_id_form_instances"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["worksheet_document_id"],
            ["documents.id"],
            name=op.f("fk_form_instances_worksheet_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_instances")),
        sa.UniqueConstraint(
            "compliance_case_id", "form_template_id", "version", name="uq_form_instances_version"
        ),
        sa.UniqueConstraint("instance_key", name="uq_form_instances_key"),
    )
    op.create_index(
        "ix_form_instances_case", "form_instances", ["compliance_case_id", "status"], unique=False
    )
    op.create_index(
        "ix_form_instances_status", "form_instances", ["status", "signature_required"], unique=False
    )
    op.create_table(
        "information_values",
        sa.Column("information_definition_id", sa.UUID(), nullable=False),
        sa.Column("legal_entity_id", sa.UUID(), nullable=True),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=True),
        sa.Column("license_id", sa.UUID(), nullable=True),
        sa.Column("vendor_organization_id", sa.UUID(), nullable=True),
        sa.Column("compliance_case_id", sa.UUID(), nullable=True),
        sa.Column("value_version", sa.Integer(), nullable=False),
        sa.Column("value_encrypted", sa.Text(), nullable=True),
        sa.Column("value_plain", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("value_fingerprint", sa.Text(), nullable=False),
        sa.Column("display_value_redacted", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("owner_actor", sa.Text(), nullable=True),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("created_by_actor", sa.Text(), nullable=True),
        sa.Column("approved_by_actor", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cross_entity_approved_by_actor", sa.Text(), nullable=True),
        sa.Column("cross_entity_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_value_id", sa.UUID(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'EXPIRED', 'SUPERSEDED', 'REJECTED')",
            name=op.f("ck_information_values_status"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name=op.f("ck_information_values_validity_range"),
        ),
        sa.CheckConstraint("value_version >= 1", name=op.f("ck_information_values_version")),
        sa.ForeignKeyConstraint(
            ["compliance_case_id"],
            ["compliance_cases.id"],
            name=op.f("fk_information_values_compliance_case_id_compliance_cases"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["information_definition_id"],
            ["information_definitions.id"],
            name=op.f("fk_information_values_information_definition_id_information_definitions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdictions.id"],
            name=op.f("fk_information_values_jurisdiction_id_jurisdictions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["legal_entity_id"],
            ["legal_entities.id"],
            name=op.f("fk_information_values_legal_entity_id_legal_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["license_id"],
            ["license_inventory.id"],
            name=op.f("fk_information_values_license_id_license_inventory"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["documents.id"],
            name=op.f("fk_information_values_source_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_value_id"],
            ["information_values.id"],
            name=op.f("fk_information_values_superseded_by_value_id_information_values"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_organization_id"],
            ["organizations.id"],
            name=op.f("fk_information_values_vendor_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_information_values")),
    )
    op.create_index(
        "ix_information_values_entity",
        "information_values",
        ["legal_entity_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_information_values_owner", "information_values", ["owner_actor", "status"], unique=False
    )
    op.create_index(
        "ix_information_values_status", "information_values", ["status", "valid_to"], unique=False
    )
    op.create_index(
        "uq_information_values_approved",
        "information_values",
        [
            "information_definition_id",
            sa.literal_column(
                "COALESCE(legal_entity_id, '00000000-0000-0000-0000-000000000000'::uuid)"
            ),
            sa.literal_column(
                "COALESCE(jurisdiction_id, '00000000-0000-0000-0000-000000000000'::uuid)"
            ),
        ],
        unique=True,
        postgresql_where=sa.text("status = 'APPROVED'"),
    )
    op.create_index(
        "uq_information_values_version",
        "information_values",
        [
            "information_definition_id",
            sa.literal_column(
                "COALESCE(legal_entity_id, '00000000-0000-0000-0000-000000000000'::uuid)"
            ),
            sa.literal_column(
                "COALESCE(jurisdiction_id, '00000000-0000-0000-0000-000000000000'::uuid)"
            ),
            "value_version",
        ],
        unique=True,
    )
    op.create_table(
        "licensing_jobs",
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("legal_entity_id", sa.UUID(), nullable=True),
        sa.Column("compliance_case_id", sa.UUID(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("6"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED_RETRYABLE', 'FAILED_REVIEW', 'CANCELLED')",
            name=op.f("ck_licensing_jobs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["compliance_case_id"],
            ["compliance_cases.id"],
            name=op.f("fk_licensing_jobs_compliance_case_id_compliance_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["legal_entity_id"],
            ["legal_entities.id"],
            name=op.f("fk_licensing_jobs_legal_entity_id_legal_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_licensing_jobs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_licensing_jobs_idempotency_key")),
    )
    op.create_index(
        "ix_licensing_jobs_claim",
        "licensing_jobs",
        ["status", "available_at", "priority"],
        unique=False,
    )
    op.create_index(
        "ix_licensing_jobs_type", "licensing_jobs", ["job_type", "status"], unique=False
    )
    op.create_table(
        "case_information_requests",
        sa.Column("compliance_case_id", sa.UUID(), nullable=False),
        sa.Column("information_definition_id", sa.UUID(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("requested_from_actor", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_value_id", sa.UUID(), nullable=True),
        sa.Column("source_email_id", sa.UUID(), nullable=True),
        sa.Column("source_vendor_question", sa.Text(), nullable=True),
        sa.Column("provided_to_vendor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'REQUESTED', 'ANSWER_PROPOSED', 'ANSWER_REVIEW', 'ANSWER_APPROVED', 'PROVIDED_TO_VENDOR', 'NOT_APPLICABLE', 'CANCELLED')",
            name=op.f("ck_case_information_requests_status"),
        ),
        sa.ForeignKeyConstraint(
            ["compliance_case_id"],
            ["compliance_cases.id"],
            name=op.f("fk_case_information_requests_compliance_case_id_compliance_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["information_definition_id"],
            ["information_definitions.id"],
            name=op.f(
                "fk_case_information_requests_information_definition_id_information_definitions"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["response_value_id"],
            ["information_values.id"],
            name=op.f("fk_case_information_requests_response_value_id_information_values"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_email_id"],
            ["emails.id"],
            name=op.f("fk_case_information_requests_source_email_id_emails"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_information_requests")),
    )
    op.create_index(
        "ix_case_information_requests_assignee",
        "case_information_requests",
        ["requested_from_actor", "status"],
        unique=False,
    )
    op.create_index(
        "ix_case_information_requests_case",
        "case_information_requests",
        ["compliance_case_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_case_information_requests_due", "case_information_requests", ["due_at"], unique=False
    )
    op.create_table(
        "deadline_events",
        sa.Column("deadline_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("previous_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("new_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('CREATED', 'RECALCULATED', 'MANUALLY_OVERRIDDEN', 'OWNER_CHANGED', 'ESCALATED', 'COMPLETED', 'WAIVED', 'SUPERSEDED', 'CANCELLED')",
            name=op.f("ck_deadline_events_type"),
        ),
        sa.ForeignKeyConstraint(
            ["deadline_id"],
            ["compliance_deadlines.id"],
            name=op.f("fk_deadline_events_deadline_id_compliance_deadlines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deadline_events")),
    )
    op.create_index(
        "ix_deadline_events_deadline",
        "deadline_events",
        ["deadline_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "document_packet_items",
        sa.Column("document_packet_id", sa.UUID(), nullable=False),
        sa.Column("packet_item_key", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("document_version_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("inclusion_reason", sa.Text(), nullable=True),
        sa.Column("document_sha256", sa.Text(), nullable=True),
        sa.Column("filename_in_archive", sa.Text(), nullable=True),
        sa.Column("required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("override_by_actor", sa.Text(), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('MATCHED', 'MISSING', 'EXPIRED', 'UNAPPROVED', 'WRONG_ENTITY', 'WRONG_JURISDICTION', 'INCLUDED', 'EXCLUDED')",
            name=op.f("ck_document_packet_items_status"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_packet_items_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_packet_id"],
            ["document_packets.id"],
            name=op.f("fk_document_packet_items_document_packet_id_document_packets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_document_packet_items_document_version_id_document_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_packet_items")),
        sa.UniqueConstraint(
            "document_packet_id", "packet_item_key", name="uq_document_packet_items_key"
        ),
    )
    op.create_index(
        "ix_document_packet_items_document", "document_packet_items", ["document_id"], unique=False
    )
    op.create_index(
        "ix_document_packet_items_packet",
        "document_packet_items",
        ["document_packet_id", "sort_order"],
        unique=False,
    )
    op.create_table(
        "information_value_usage",
        sa.Column("information_value_id", sa.UUID(), nullable=False),
        sa.Column("compliance_case_id", sa.UUID(), nullable=True),
        sa.Column("form_instance_id", sa.UUID(), nullable=True),
        sa.Column("packet_id", sa.UUID(), nullable=True),
        sa.Column("used_by_actor", sa.Text(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("used_value_version", sa.Integer(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('FORM_PREFILL', 'PACKET_ASSEMBLY', 'VENDOR_ANSWER', 'CASE_REFERENCE', 'WORKSHEET_EXPORT', 'MANUAL_LOOKUP')",
            name=op.f("ck_information_value_usage_purpose"),
        ),
        sa.ForeignKeyConstraint(
            ["compliance_case_id"],
            ["compliance_cases.id"],
            name=op.f("fk_information_value_usage_compliance_case_id_compliance_cases"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["form_instance_id"],
            ["form_instances.id"],
            name=op.f("fk_information_value_usage_form_instance_id_form_instances"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["information_value_id"],
            ["information_values.id"],
            name=op.f("fk_information_value_usage_information_value_id_information_values"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["packet_id"],
            ["document_packets.id"],
            name=op.f("fk_information_value_usage_packet_id_document_packets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_information_value_usage")),
    )
    op.create_index(
        "ix_information_value_usage_case",
        "information_value_usage",
        ["compliance_case_id"],
        unique=False,
    )
    op.create_index(
        "ix_information_value_usage_form",
        "information_value_usage",
        ["form_instance_id"],
        unique=False,
    )
    op.create_index(
        "ix_information_value_usage_value",
        "information_value_usage",
        ["information_value_id", "used_at"],
        unique=False,
    )
    op.create_table(
        "form_field_values",
        sa.Column("form_instance_id", sa.UUID(), nullable=False),
        sa.Column("form_template_field_id", sa.UUID(), nullable=False),
        sa.Column("value_encrypted", sa.Text(), nullable=True),
        sa.Column("value_plain", sa.Text(), nullable=True),
        sa.Column("display_value_redacted", sa.Text(), nullable=True),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=True),
        sa.Column("source_value_version", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reviewed_by_actor", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unresolved_reason", sa.Text(), nullable=True),
        sa.Column("information_request_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_type IN ('INFORMATION_REGISTRY', 'LEGAL_ENTITY', 'LICENSE_INVENTORY', 'COMPLIANCE_CASE', 'DOCUMENT_METADATA', 'MANUAL_INPUT', 'SIGNATURE_REQUIRED', 'CALCULATED')",
            name=op.f("ck_form_field_values_source_type"),
        ),
        sa.CheckConstraint(
            "status IN ('AUTO_FILLED', 'MANUALLY_FILLED', 'NEEDS_INFORMATION', 'NEEDS_REVIEW', 'APPROVED', 'SIGNATURE_REQUIRED', 'MANUAL_ONLY', 'NOT_APPLICABLE')",
            name=op.f("ck_form_field_values_status"),
        ),
        sa.ForeignKeyConstraint(
            ["form_instance_id"],
            ["form_instances.id"],
            name=op.f("fk_form_field_values_form_instance_id_form_instances"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["form_template_field_id"],
            ["form_template_fields.id"],
            name=op.f("fk_form_field_values_form_template_field_id_form_template_fields"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["information_request_id"],
            ["case_information_requests.id"],
            name=op.f("fk_form_field_values_information_request_id_case_information_requests"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_field_values")),
        sa.UniqueConstraint(
            "form_instance_id", "form_template_field_id", name="uq_form_field_values_field"
        ),
    )
    op.create_index(
        "ix_form_field_values_instance",
        "form_field_values",
        ["form_instance_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    # Break the requirement_sources <-> requirement_source_snapshots cycle first,
    # otherwise neither table can be dropped.
    op.drop_constraint(
        "fk_requirement_sources_current_snapshot", "requirement_sources", type_="foreignkey"
    )
    op.drop_index("ix_form_field_values_instance", table_name="form_field_values")
    op.drop_table("form_field_values")
    op.drop_index("ix_information_value_usage_value", table_name="information_value_usage")
    op.drop_index("ix_information_value_usage_form", table_name="information_value_usage")
    op.drop_index("ix_information_value_usage_case", table_name="information_value_usage")
    op.drop_table("information_value_usage")
    op.drop_index("ix_document_packet_items_packet", table_name="document_packet_items")
    op.drop_index("ix_document_packet_items_document", table_name="document_packet_items")
    op.drop_table("document_packet_items")
    op.drop_index("ix_deadline_events_deadline", table_name="deadline_events")
    op.drop_table("deadline_events")
    op.drop_index("ix_case_information_requests_due", table_name="case_information_requests")
    op.drop_index("ix_case_information_requests_case", table_name="case_information_requests")
    op.drop_index("ix_case_information_requests_assignee", table_name="case_information_requests")
    op.drop_table("case_information_requests")
    op.drop_index("ix_licensing_jobs_type", table_name="licensing_jobs")
    op.drop_index("ix_licensing_jobs_claim", table_name="licensing_jobs")
    op.drop_table("licensing_jobs")
    op.drop_index("uq_information_values_version", table_name="information_values")
    op.drop_index(
        "uq_information_values_approved",
        table_name="information_values",
        postgresql_where=sa.text("status = 'APPROVED'"),
    )
    op.drop_index("ix_information_values_status", table_name="information_values")
    op.drop_index("ix_information_values_owner", table_name="information_values")
    op.drop_index("ix_information_values_entity", table_name="information_values")
    op.drop_table("information_values")
    op.drop_index("ix_form_instances_status", table_name="form_instances")
    op.drop_index("ix_form_instances_case", table_name="form_instances")
    op.drop_table("form_instances")
    op.drop_index("ix_document_packets_case", table_name="document_packets")
    op.drop_table("document_packets")
    op.drop_index(
        "uq_compliance_deadlines_materialization",
        table_name="compliance_deadlines",
        postgresql_where=sa.text("materialization_key IS NOT NULL"),
    )
    op.drop_index("ix_compliance_deadlines_owner", table_name="compliance_deadlines")
    op.drop_index("ix_compliance_deadlines_obligation", table_name="compliance_deadlines")
    op.drop_index("ix_compliance_deadlines_due", table_name="compliance_deadlines")
    op.drop_index("ix_compliance_deadlines_case", table_name="compliance_deadlines")
    op.drop_table("compliance_deadlines")
    op.drop_index("ix_case_stage_events_case", table_name="compliance_case_stage_events")
    op.drop_table("compliance_case_stage_events")
    op.drop_index("ix_compliance_cases_target", table_name="compliance_cases")
    op.drop_index("ix_compliance_cases_stage", table_name="compliance_cases")
    op.drop_index("ix_compliance_cases_owner", table_name="compliance_cases")
    op.drop_index("ix_compliance_cases_obligation", table_name="compliance_cases")
    op.drop_index("ix_compliance_cases_entity", table_name="compliance_cases")
    op.drop_table("compliance_cases")
    op.drop_index(
        "uq_form_field_mappings_active",
        table_name="form_field_mappings",
        postgresql_where=sa.text("mapping_status = 'APPROVED'"),
    )
    op.drop_index("ix_form_field_mappings_source", table_name="form_field_mappings")
    op.drop_index("ix_form_field_mappings_field", table_name="form_field_mappings")
    op.drop_table("form_field_mappings")
    op.drop_index("ix_compliance_obligations_type", table_name="compliance_obligations")
    op.drop_index("ix_compliance_obligations_license", table_name="compliance_obligations")
    op.drop_index("ix_compliance_obligations_entity", table_name="compliance_obligations")
    op.drop_index("ix_compliance_obligations_due", table_name="compliance_obligations")
    op.drop_table("compliance_obligations")
    op.drop_index("ix_tracker_import_rows_target", table_name="tracker_import_rows")
    op.drop_index("ix_tracker_import_rows_run", table_name="tracker_import_rows")
    op.drop_index("ix_tracker_import_rows_fingerprint", table_name="tracker_import_rows")
    op.drop_table("tracker_import_rows")
    op.drop_index("ix_license_status_events_license", table_name="license_status_events")
    op.drop_table("license_status_events")
    op.drop_index("ix_license_bonds_license", table_name="license_bonds")
    op.drop_index("ix_license_bonds_expiration", table_name="license_bonds")
    op.drop_table("license_bonds")
    op.drop_index("ix_form_template_fields_template", table_name="form_template_fields")
    op.drop_table("form_template_fields")
    op.drop_index("ix_tracker_import_runs_status", table_name="tracker_import_runs")
    op.drop_index("ix_tracker_import_runs_hash", table_name="tracker_import_runs")
    op.drop_table("tracker_import_runs")
    op.drop_index(
        "uq_license_inventory_live_authority",
        table_name="license_inventory",
        postgresql_where=sa.text(
            "represents_additional_authority = false AND current_status IN ('APPLICATION_IN_PROGRESS', 'PENDING_REGULATOR', 'APPROVED', 'ACTIVE', 'RENEWAL_IN_PROGRESS', 'REINSTATING', 'SUSPENDED')"
        ),
    )
    op.drop_index("ix_license_inventory_renewal_due", table_name="license_inventory")
    op.drop_index("ix_license_inventory_jurisdiction", table_name="license_inventory")
    op.drop_index("ix_license_inventory_expiration", table_name="license_inventory")
    op.drop_index("ix_license_inventory_entity", table_name="license_inventory")
    op.drop_table("license_inventory")
    op.drop_index("ix_form_templates_scope", table_name="form_templates")
    op.drop_index("ix_form_templates_family", table_name="form_templates")
    op.drop_table("form_templates")
    op.drop_index("ix_packet_template_items_template", table_name="packet_template_items")
    op.drop_table("packet_template_items")
    op.drop_index("ix_assessment_overrides_result", table_name="assessment_overrides")
    op.drop_table("assessment_overrides")
    op.drop_index("ix_requirement_rule_sources_snapshot", table_name="requirement_rule_sources")
    op.drop_table("requirement_rule_sources")
    op.drop_index(
        "uq_requirement_assessment_results_scope", table_name="requirement_assessment_results"
    )
    op.drop_index("ix_requirement_results_review", table_name="requirement_assessment_results")
    op.drop_index("ix_requirement_results_outcome", table_name="requirement_assessment_results")
    op.drop_table("requirement_assessment_results")
    op.drop_index("ix_packet_templates_scope", table_name="packet_templates")
    op.drop_table("packet_templates")
    op.drop_index(
        "ix_requirement_source_snapshots_review", table_name="requirement_source_snapshots"
    )
    op.drop_index("ix_requirement_source_snapshots_hash", table_name="requirement_source_snapshots")
    op.drop_table("requirement_source_snapshots")
    op.drop_index("ix_requirement_assessments_fingerprint", table_name="requirement_assessments")
    op.drop_index("ix_requirement_assessments_entity", table_name="requirement_assessments")
    op.drop_table("requirement_assessments")
    op.drop_index("ix_requirement_sources_verification", table_name="requirement_sources")
    op.drop_index("ix_requirement_sources_jurisdiction", table_name="requirement_sources")
    op.drop_table("requirement_sources")
    op.drop_index("ix_requirement_rules_scope", table_name="requirement_rules")
    op.drop_index("ix_requirement_rules_enabled", table_name="requirement_rules")
    op.drop_table("requirement_rules")
    op.drop_index(
        "uq_operating_profiles_active",
        table_name="operating_profiles",
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.drop_table("operating_profiles")
    op.drop_index(
        "ix_information_owner_assignments_owner", table_name="information_owner_assignments"
    )
    op.drop_table("information_owner_assignments")
    op.drop_index("ix_deadline_rules_status", table_name="deadline_rules")
    op.drop_index("ix_deadline_rules_scope", table_name="deadline_rules")
    op.drop_table("deadline_rules")
    op.drop_index(
        "uq_requirement_rule_sets_active",
        table_name="requirement_rule_sets",
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.drop_table("requirement_rule_sets")
    op.drop_index("ix_licensing_notifications_recipient", table_name="licensing_notifications")
    op.drop_index("ix_licensing_notifications_entity", table_name="licensing_notifications")
    op.drop_table("licensing_notifications")
    op.drop_table("license_types")
    op.drop_index("ix_legal_entities_status", table_name="legal_entities")
    op.drop_table("legal_entities")
    op.drop_index("ix_jurisdictions_parent", table_name="jurisdictions")
    op.drop_table("jurisdictions")
    op.drop_index("ix_information_definitions_category", table_name="information_definitions")
    op.drop_table("information_definitions")
    op.drop_table("business_activities")

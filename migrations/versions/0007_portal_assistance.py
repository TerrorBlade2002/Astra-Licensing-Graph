"""Human-supervised portal assistance and submission evidence.

No table stores passwords, MFA values, cookies, payment credentials, or raw
browser storage. Browser state is represented only by an optional encrypted
reference and is removed when a session closes.

Revision ID: 0007_portal_assistance
Revises: 0006_licensing_lifecycle
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_portal_assistance"
down_revision: str | None = "0006_licensing_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def _id() -> sa.Column:
    return sa.Column("id", sa.UUID(), nullable=False)


def _enum(column: str, values: tuple[str, ...], name: str) -> sa.CheckConstraint:
    quoted = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({quoted})", name=op.f(f"ck_{name}"))


def upgrade() -> None:
    op.create_table(
        "portal_definitions",
        sa.Column("portal_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("portal_type", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("hostname", sa.Text(), nullable=False),
        sa.Column("owner_organization_id", sa.UUID(), nullable=True),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=True),
        sa.Column(
            "supported_filing_types",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("approved_automation_level", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("data_classification", sa.Text(), nullable=False),
        sa.Column("credential_model", sa.Text(), nullable=False),
        sa.Column("mfa_model", sa.Text(), nullable=True),
        sa.Column("captcha_expected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("terms_review_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("terms_review_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "final_submit_human_only", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("payment_human_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("attestation_human_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("signature_human_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        _id(),
        _created_at(),
        _updated_at(),
        _enum(
            "portal_type",
            (
                "NMLS",
                "STATE_REGULATOR",
                "LOCAL_REGULATOR",
                "SECRETARY_OF_STATE",
                "BOND_PROVIDER",
                "LICENSING_VENDOR",
                "PAYMENT",
                "DOCUMENT_UPLOAD",
                "OTHER",
            ),
            "portal_definitions_portal_type",
        ),
        _enum(
            "approved_automation_level",
            (
                "PREPARE_ONLY",
                "NAVIGATION_ASSIST",
                "ASSISTED_ENTRY",
                "UPLOAD_ASSIST",
                "PRE_SUBMISSION_ASSIST",
                "API_ASSISTED",
            ),
            "portal_definitions_automation_level",
        ),
        _enum(
            "status",
            (
                "DISCOVERED",
                "REVIEW_PENDING",
                "APPROVED_PREPARE_ONLY",
                "APPROVED_ASSISTED",
                "APPROVED_API",
                "AUTOMATION_PROHIBITED",
                "TEMPORARILY_SUSPENDED",
                "EXPIRED",
                "RETIRED",
            ),
            "portal_definitions_status",
        ),
        _enum(
            "credential_model",
            (
                "INDIVIDUAL_USER_LOGIN",
                "ORGANIZATION_USER_LOGIN",
                "APPROVED_SERVICE_ACCOUNT",
                "OAUTH_DELEGATED",
                "OAUTH_APPLICATION",
                "API_KEY",
                "CERTIFICATE",
                "NO_LOGIN",
                "UNKNOWN",
            ),
            "portal_definitions_credential_model",
        ),
        sa.ForeignKeyConstraint(
            ["owner_organization_id"], ["organizations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["jurisdiction_id"], ["jurisdictions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_definitions")),
        sa.UniqueConstraint("portal_key", name=op.f("uq_portal_definitions_portal_key")),
    )
    op.create_index("ix_portal_definitions_status", "portal_definitions", ["status"], unique=False)
    op.create_index(
        "ix_portal_definitions_hostname", "portal_definitions", ["hostname"], unique=False
    )

    op.create_table(
        "portal_review_versions",
        sa.Column("portal_definition_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("terms_reference", sa.Text(), nullable=True),
        sa.Column("terms_sha256", sa.Text(), nullable=True),
        sa.Column("terms_effective_date", sa.Date(), nullable=True),
        sa.Column(
            "allowed_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "prohibited_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "approved_filing_types",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "approved_entity_ids",
            postgresql.ARRAY(sa.UUID()),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "security_findings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by_compliance", sa.Text(), nullable=True),
        sa.Column("reviewed_by_security", sa.Text(), nullable=True),
        sa.Column("approved_by_actor", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        _id(),
        _created_at(),
        _enum(
            "status",
            ("DRAFT", "APPROVED", "SUSPENDED", "EXPIRED", "SUPERSEDED", "REJECTED"),
            "portal_review_versions_status",
        ),
        sa.ForeignKeyConstraint(
            ["portal_definition_id"], ["portal_definitions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_review_versions")),
        sa.UniqueConstraint("portal_definition_id", "version", name="uq_portal_review_version"),
    )
    op.create_index(
        "uq_portal_review_active",
        "portal_review_versions",
        ["portal_definition_id"],
        unique=True,
        postgresql_where=sa.text("status = 'APPROVED'"),
    )
    op.create_index(
        "ix_portal_review_validity",
        "portal_review_versions",
        ["valid_to", "status"],
        unique=False,
    )

    op.create_table(
        "portal_user_authorizations",
        sa.Column("portal_definition_id", sa.UUID(), nullable=False),
        sa.Column("user_principal_id", sa.UUID(), nullable=False),
        sa.Column("external_account_reference", sa.Text(), nullable=True),
        sa.Column("portal_role", sa.Text(), nullable=True),
        sa.Column("authorization_status", sa.Text(), nullable=False),
        sa.Column(
            "authorized_filing_types",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "authorized_entity_ids",
            postgresql.ARRAY(sa.UUID()),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        _id(),
        _created_at(),
        _updated_at(),
        _enum(
            "authorization_status",
            ("PENDING", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED"),
            "portal_user_authorizations_status",
        ),
        sa.ForeignKeyConstraint(
            ["portal_definition_id"], ["portal_definitions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_principal_id"], ["user_principals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_user_authorizations")),
        sa.UniqueConstraint(
            "portal_definition_id",
            "user_principal_id",
            name="uq_portal_user_authorization",
        ),
    )
    op.create_index(
        "ix_portal_user_authorizations_status",
        "portal_user_authorizations",
        ["authorization_status", "expires_at"],
        unique=False,
    )

    op.create_table(
        "portal_adapter_versions",
        sa.Column("portal_definition_id", sa.UUID(), nullable=False),
        sa.Column("adapter_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "supported_routes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "locator_contract",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("field_mapping_version", sa.Text(), nullable=True),
        sa.Column("test_fixture_version", sa.Text(), nullable=True),
        sa.Column("source_revision", sa.Text(), nullable=True),
        sa.Column("approved_by_actor", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        _id(),
        _created_at(),
        _enum(
            "status",
            ("DRAFT", "TESTING", "ACTIVE", "SUSPENDED", "RETIRED"),
            "portal_adapter_versions_status",
        ),
        sa.ForeignKeyConstraint(
            ["portal_definition_id"], ["portal_definitions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_adapter_versions")),
        sa.UniqueConstraint(
            "portal_definition_id",
            "adapter_key",
            "version",
            name="uq_portal_adapter_version",
        ),
    )
    op.create_index(
        "uq_portal_adapter_active",
        "portal_adapter_versions",
        ["portal_definition_id", "adapter_key"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "portal_field_mappings",
        sa.Column("portal_adapter_version_id", sa.UUID(), nullable=False),
        sa.Column("filing_type", sa.Text(), nullable=False),
        sa.Column("portal_field_key", sa.Text(), nullable=False),
        sa.Column("portal_label", sa.Text(), nullable=True),
        sa.Column("locator_strategy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("transformation_key", sa.Text(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("sensitivity", sa.Text(), nullable=False),
        sa.Column("human_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "requires_fresh_confirmation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("allowed_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "validation_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        _id(),
        _created_at(),
        _enum(
            "source_type",
            (
                "FORM_INSTANCE_FIELD",
                "INFORMATION_REGISTRY",
                "LEGAL_ENTITY",
                "LICENSE_INVENTORY",
                "COMPLIANCE_CASE",
                "DOCUMENT_METADATA",
                "MANUAL_OPERATOR_INPUT",
                "CALCULATED",
                "ATTESTATION",
                "SIGNATURE",
                "PAYMENT",
            ),
            "portal_field_mappings_source_type",
        ),
        sa.ForeignKeyConstraint(
            ["portal_adapter_version_id"],
            ["portal_adapter_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_field_mappings")),
        sa.UniqueConstraint(
            "portal_adapter_version_id",
            "filing_type",
            "portal_field_key",
            name="uq_portal_field_mapping",
        ),
    )
    op.create_index(
        "ix_portal_field_mapping_order",
        "portal_field_mappings",
        ["portal_adapter_version_id", "sort_order"],
        unique=False,
    )

    op.create_table(
        "portal_runs",
        sa.Column("run_key", sa.Text(), nullable=False),
        sa.Column("portal_definition_id", sa.UUID(), nullable=False),
        sa.Column("portal_review_version_id", sa.UUID(), nullable=False),
        sa.Column("portal_adapter_version_id", sa.UUID(), nullable=True),
        sa.Column("compliance_case_id", sa.UUID(), nullable=False),
        sa.Column("legal_entity_id", sa.UUID(), nullable=False),
        sa.Column("license_id", sa.UUID(), nullable=True),
        sa.Column("form_instance_id", sa.UUID(), nullable=True),
        sa.Column("document_packet_id", sa.UUID(), nullable=True),
        sa.Column("filing_type", sa.Text(), nullable=False),
        sa.Column("automation_level", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_stage", sa.Text(), nullable=False),
        sa.Column("assigned_operator_id", sa.UUID(), nullable=True),
        sa.Column("assigned_signatory_id", sa.UUID(), nullable=True),
        sa.Column("assigned_payment_approver_id", sa.UUID(), nullable=True),
        sa.Column("earliest_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_by_actor", sa.Text(), nullable=True),
        _id(),
        _created_at(),
        _updated_at(),
        _enum(
            "automation_level",
            (
                "PREPARE_ONLY",
                "NAVIGATION_ASSIST",
                "ASSISTED_ENTRY",
                "UPLOAD_ASSIST",
                "PRE_SUBMISSION_ASSIST",
                "API_ASSISTED",
            ),
            "portal_runs_automation_level",
        ),
        _enum(
            "status",
            (
                "PLANNED",
                "READY",
                "WAITING_OPERATOR",
                "SESSION_ACTIVE",
                "WAITING_LOGIN",
                "WAITING_TERMS_ACCEPTANCE",
                "WAITING_MFA",
                "WAITING_CAPTCHA",
                "ENTRY_IN_PROGRESS",
                "UPLOAD_IN_PROGRESS",
                "VALIDATION_REQUIRED",
                "DISCREPANCIES_FOUND",
                "READY_FOR_PRE_SUBMISSION_REVIEW",
                "PRE_SUBMISSION_APPROVED",
                "WAITING_ATTESTATION",
                "WAITING_SIGNATURE",
                "WAITING_PAYMENT",
                "WAITING_FINAL_SUBMIT",
                "SUBMISSION_RESULT_PENDING",
                "SUBMITTED",
                "SUBMISSION_FAILED",
                "COMPLETED",
                "BLOCKED",
                "CANCELLED",
                "FAILED_REVIEW",
            ),
            "portal_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["portal_definition_id"], ["portal_definitions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["portal_review_version_id"], ["portal_review_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["portal_adapter_version_id"], ["portal_adapter_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["compliance_case_id"], ["compliance_cases.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["legal_entity_id"], ["legal_entities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["license_id"], ["license_inventory.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["form_instance_id"], ["form_instances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["document_packet_id"], ["document_packets.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_operator_id"], ["user_principals.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_signatory_id"], ["user_principals.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_payment_approver_id"], ["user_principals.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_runs")),
        sa.UniqueConstraint("run_key", name=op.f("uq_portal_runs_run_key")),
    )
    op.create_index("ix_portal_runs_queue", "portal_runs", ["status", "deadline_at"], unique=False)
    op.create_index("ix_portal_runs_case", "portal_runs", ["compliance_case_id"], unique=False)
    op.create_index(
        "ix_portal_runs_operator",
        "portal_runs",
        ["assigned_operator_id", "status"],
        unique=False,
    )

    op.create_table(
        "browser_sessions",
        sa.Column("portal_run_id", sa.UUID(), nullable=False),
        sa.Column("operator_user_id", sa.UUID(), nullable=False),
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("session_status", sa.Text(), nullable=False),
        sa.Column("browser_type", sa.Text(), nullable=False),
        sa.Column("ephemeral_profile_id", sa.Text(), nullable=False),
        sa.Column("encrypted_session_reference", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.Text(), nullable=True),
        _id(),
        _created_at(),
        _enum(
            "session_status",
            (
                "REQUESTED",
                "STARTING",
                "ACTIVE_AUTOMATION",
                "ACTIVE_HUMAN_CONTROL",
                "PAUSED",
                "EXPIRED",
                "CLOSED",
                "FAILED",
            ),
            "browser_sessions_status",
        ),
        sa.ForeignKeyConstraint(["portal_run_id"], ["portal_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_user_id"], ["user_principals.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_browser_sessions")),
    )
    op.create_index(
        "uq_browser_sessions_active_run",
        "browser_sessions",
        ["portal_run_id"],
        unique=True,
        postgresql_where=sa.text(
            "session_status IN "
            "('REQUESTED','STARTING','ACTIVE_AUTOMATION','ACTIVE_HUMAN_CONTROL','PAUSED')"
        ),
    )
    op.create_index(
        "ix_browser_sessions_expiry",
        "browser_sessions",
        ["session_status", "expires_at"],
        unique=False,
    )

    op.create_table(
        "portal_run_steps",
        sa.Column("portal_run_id", sa.UUID(), nullable=False),
        sa.Column("step_key", sa.Text(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("automation_mode", sa.Text(), nullable=False),
        sa.Column("page_category", sa.Text(), nullable=True),
        sa.Column("safe_url_path", sa.Text(), nullable=True),
        sa.Column("locator_contract_version", sa.Text(), nullable=True),
        sa.Column("expected_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("observed_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operator_actor", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        _id(),
        _created_at(),
        _enum(
            "step_type",
            (
                "NAVIGATE",
                "LOGIN_HANDOFF",
                "TERMS_HANDOFF",
                "MFA_HANDOFF",
                "CAPTCHA_HANDOFF",
                "FIELD_ENTRY",
                "DOCUMENT_UPLOAD",
                "VALIDATION",
                "PRE_SUBMISSION_CAPTURE",
                "ATTESTATION_HANDOFF",
                "SIGNATURE_HANDOFF",
                "PAYMENT_HANDOFF",
                "FINAL_SUBMIT_HANDOFF",
                "SUBMISSION_RESULT_CAPTURE",
            ),
            "portal_run_steps_type",
        ),
        _enum(
            "status",
            (
                "PENDING",
                "RUNNING",
                "WAITING_HUMAN",
                "COMPLETED",
                "FAILED_RETRYABLE",
                "FAILED_REVIEW",
                "CANCELLED",
            ),
            "portal_run_steps_status",
        ),
        sa.ForeignKeyConstraint(["portal_run_id"], ["portal_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_run_steps")),
        sa.UniqueConstraint("portal_run_id", "sequence_number", name="uq_portal_run_step_sequence"),
    )
    op.create_index(
        "ix_portal_run_steps_timeline",
        "portal_run_steps",
        ["portal_run_id", "sequence_number"],
        unique=False,
    )

    op.create_table(
        "portal_run_fields",
        sa.Column("portal_run_id", sa.UUID(), nullable=False),
        sa.Column("portal_field_mapping_id", sa.UUID(), nullable=True),
        sa.Column("portal_field_key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("approved_source_type", sa.Text(), nullable=True),
        sa.Column("approved_source_record_id", sa.UUID(), nullable=True),
        sa.Column("approved_value_fingerprint", sa.Text(), nullable=True),
        sa.Column("entered_value_fingerprint", sa.Text(), nullable=True),
        sa.Column("displayed_value_redacted", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("entered_by", sa.Text(), nullable=True),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discrepancy_code", sa.Text(), nullable=True),
        sa.Column("discrepancy_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _id(),
        _created_at(),
        _updated_at(),
        _enum(
            "status",
            (
                "PENDING",
                "AUTO_ENTERED",
                "HUMAN_ENTERED",
                "HUMAN_ONLY",
                "VERIFIED",
                "DISCREPANCY",
                "REJECTED",
                "NOT_APPLICABLE",
                "BLOCKED",
            ),
            "portal_run_fields_status",
        ),
        sa.ForeignKeyConstraint(["portal_run_id"], ["portal_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["portal_field_mapping_id"], ["portal_field_mappings.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_run_fields")),
        sa.UniqueConstraint("portal_run_id", "portal_field_key", name="uq_portal_run_field"),
    )
    op.create_index(
        "ix_portal_run_fields_status",
        "portal_run_fields",
        ["portal_run_id", "status"],
        unique=False,
    )

    op.create_table(
        "portal_run_documents",
        sa.Column("portal_run_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("expected_filename", sa.Text(), nullable=False),
        sa.Column("expected_sha256", sa.Text(), nullable=False),
        sa.Column("portal_document_category", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("portal_upload_reference", sa.Text(), nullable=True),
        sa.Column("portal_display_name", sa.Text(), nullable=True),
        sa.Column("portal_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("selected_by_actor", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discrepancy_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _id(),
        _created_at(),
        _updated_at(),
        _enum(
            "status",
            (
                "SELECTED",
                "VALIDATED",
                "UPLOAD_PENDING",
                "UPLOADING",
                "UPLOADED",
                "VERIFIED",
                "FAILED_RETRYABLE",
                "FAILED_REVIEW",
                "REMOVED",
            ),
            "portal_run_documents_status",
        ),
        sa.ForeignKeyConstraint(["portal_run_id"], ["portal_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_run_documents")),
        sa.UniqueConstraint(
            "portal_run_id",
            "document_version_id",
            name="uq_portal_run_document_version",
        ),
    )
    op.create_index(
        "ix_portal_run_documents_status",
        "portal_run_documents",
        ["portal_run_id", "status"],
        unique=False,
    )

    op.create_table(
        "human_handoffs",
        sa.Column("portal_run_id", sa.UUID(), nullable=False),
        sa.Column("browser_session_id", sa.UUID(), nullable=True),
        sa.Column("handoff_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("requested_from_user_id", sa.UUID(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("operator_confirmation", sa.Text(), nullable=True),
        sa.Column("evidence_reference", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        _id(),
        _created_at(),
        _enum(
            "handoff_type",
            (
                "LOGIN",
                "TERMS_ACCEPTANCE",
                "MFA",
                "CAPTCHA",
                "SENSITIVE_FIELD",
                "ATTESTATION",
                "SIGNATURE",
                "PAYMENT",
                "FINAL_SUBMIT",
                "UNEXPECTED_PAGE",
                "PORTAL_ERROR",
            ),
            "human_handoffs_type",
        ),
        _enum(
            "status",
            ("REQUESTED", "ACCEPTED", "ACTIVE", "COMPLETED", "DECLINED", "EXPIRED", "FAILED"),
            "human_handoffs_status",
        ),
        sa.ForeignKeyConstraint(["portal_run_id"], ["portal_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["browser_session_id"], ["browser_sessions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["requested_from_user_id"], ["user_principals.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_human_handoffs")),
    )
    op.create_index(
        "ix_human_handoffs_queue",
        "human_handoffs",
        ["status", "requested_from_user_id", "expires_at"],
        unique=False,
    )

    op.create_table(
        "pre_submission_snapshots",
        sa.Column("portal_run_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("form_instance_version", sa.Integer(), nullable=True),
        sa.Column("field_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("document_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "portal_validation_messages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "discrepancy_report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "screenshot_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("snapshot_sha256", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_by_actor", sa.Text(), nullable=True),
        sa.Column("reviewed_by_actor", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        _id(),
        _created_at(),
        _enum(
            "status",
            (
                "DRAFT",
                "DISCREPANCIES_FOUND",
                "READY_FOR_REVIEW",
                "APPROVED",
                "REJECTED",
                "SUPERSEDED",
            ),
            "pre_submission_snapshots_status",
        ),
        sa.ForeignKeyConstraint(["portal_run_id"], ["portal_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pre_submission_snapshots")),
        sa.UniqueConstraint("portal_run_id", "version", name="uq_pre_submission_snapshot_version"),
    )
    op.create_index(
        "uq_pre_submission_snapshot_approved",
        "pre_submission_snapshots",
        ["portal_run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'APPROVED'"),
    )

    op.create_table(
        "portal_attestation_records",
        sa.Column("portal_run_id", sa.UUID(), nullable=False),
        sa.Column("attestation_type", sa.Text(), nullable=False),
        sa.Column("required_actor_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attestation_text_fingerprint", sa.Text(), nullable=True),
        sa.Column("displayed_text_reference", sa.Text(), nullable=True),
        sa.Column("completed_by_actor", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_reference", sa.Text(), nullable=True),
        _id(),
        _created_at(),
        _enum(
            "status",
            ("NOT_REQUIRED", "REQUIRED", "WAITING", "COMPLETED_BY_HUMAN", "DECLINED", "FAILED"),
            "portal_attestation_records_status",
        ),
        sa.ForeignKeyConstraint(["portal_run_id"], ["portal_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["required_actor_id"], ["user_principals.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_attestation_records")),
    )
    op.create_index(
        "ix_portal_attestation_run",
        "portal_attestation_records",
        ["portal_run_id", "status"],
        unique=False,
    )

    op.create_table(
        "portal_payment_records",
        sa.Column("portal_run_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("expected_fee_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("portal_fee_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("approved_by_actor", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_by_actor", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_reference_redacted", sa.Text(), nullable=True),
        sa.Column("receipt_document_id", sa.UUID(), nullable=True),
        _id(),
        _created_at(),
        _updated_at(),
        _enum(
            "status",
            (
                "NOT_REQUIRED",
                "ESTIMATED",
                "REVIEW_REQUIRED",
                "APPROVED",
                "WAITING_HUMAN_PAYMENT",
                "PAID_EXTERNALLY",
                "FAILED",
                "CANCELLED",
            ),
            "portal_payment_records_status",
        ),
        sa.ForeignKeyConstraint(["portal_run_id"], ["portal_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["receipt_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_payment_records")),
        sa.UniqueConstraint("portal_run_id", name="uq_portal_payment_run"),
    )

    op.create_table(
        "submission_evidence",
        sa.Column("portal_run_id", sa.UUID(), nullable=False),
        sa.Column("evidence_type", sa.Text(), nullable=False),
        sa.Column("confirmation_number", sa.Text(), nullable=True),
        sa.Column("filing_reference", sa.Text(), nullable=True),
        sa.Column("submission_status", sa.Text(), nullable=True),
        sa.Column("submitted_by_actor", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("screenshot_storage_uri", sa.Text(), nullable=True),
        sa.Column("receipt_storage_uri", sa.Text(), nullable=True),
        sa.Column("evidence_sha256", sa.Text(), nullable=True),
        sa.Column("evidence_verified_by_actor", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        _id(),
        _created_at(),
        _enum(
            "evidence_type",
            (
                "PORTAL_CONFIRMATION",
                "RECEIPT",
                "PAYMENT_RECEIPT",
                "SUBMISSION_PDF",
                "SCREENSHOT",
                "CONFIRMATION_EMAIL",
                "MANUAL_CONFIRMATION",
                "VENDOR_CONFIRMATION",
                "REGULATOR_CONFIRMATION",
            ),
            "submission_evidence_type",
        ),
        sa.ForeignKeyConstraint(["portal_run_id"], ["portal_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_submission_evidence")),
    )
    op.create_index(
        "ix_submission_evidence_run",
        "submission_evidence",
        ["portal_run_id", "evidence_type"],
        unique=False,
    )

    op.create_table(
        "portal_jobs",
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("portal_run_id", sa.UUID(), nullable=True),
        sa.Column("browser_session_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        _id(),
        _created_at(),
        _updated_at(),
        _enum(
            "job_type",
            (
                "START_BROWSER_SESSION",
                "NAVIGATE_PORTAL",
                "ENTER_FIELDS",
                "UPLOAD_DOCUMENTS",
                "RUN_PORTAL_VALIDATION",
                "CAPTURE_PRE_SUBMISSION",
                "RECONCILE_SESSION",
                "CAPTURE_SUBMISSION_RESULT",
                "CLOSE_BROWSER_SESSION",
            ),
            "portal_jobs_type",
        ),
        _enum(
            "status",
            (
                "PENDING",
                "RUNNING",
                "WAITING_HUMAN",
                "COMPLETED",
                "FAILED_RETRYABLE",
                "FAILED_REVIEW",
                "CANCELLED",
            ),
            "portal_jobs_status",
        ),
        sa.ForeignKeyConstraint(["portal_run_id"], ["portal_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["browser_session_id"], ["browser_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_jobs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_portal_jobs_idempotency_key")),
    )
    op.create_index(
        "ix_portal_jobs_claim",
        "portal_jobs",
        ["status", "available_at", "priority"],
        unique=False,
    )
    op.create_index("ix_portal_jobs_lease", "portal_jobs", ["lease_expires_at"], unique=False)


def downgrade() -> None:
    op.drop_table("portal_jobs")
    op.drop_table("submission_evidence")
    op.drop_table("portal_payment_records")
    op.drop_table("portal_attestation_records")
    op.drop_table("pre_submission_snapshots")
    op.drop_table("human_handoffs")
    op.drop_table("portal_run_documents")
    op.drop_table("portal_run_fields")
    op.drop_table("portal_run_steps")
    op.drop_table("browser_sessions")
    op.drop_table("portal_runs")
    op.drop_table("portal_field_mappings")
    op.drop_table("portal_adapter_versions")
    op.drop_table("portal_user_authorizations")
    op.drop_table("portal_review_versions")
    op.drop_table("portal_definitions")

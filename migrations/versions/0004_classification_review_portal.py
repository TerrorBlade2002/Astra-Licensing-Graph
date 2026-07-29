"""Milestone 4 classification, identity, review, and task workflow.

Revision ID: 0004_classification_review
Revises: 0003_sharepoint_documents
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_classification_review"
down_revision: str | None = "0003_sharepoint_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _updated() -> sa.Column:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.drop_constraint(op.f("ck_classifications_email_type"), "classifications", type_="check")
    op.create_check_constraint(
        op.f("ck_classifications_email_type"),
        "classifications",
        "email_type IN ('missing_information_request','renewal_notice','bond_correspondence','annual_report_or_assessment','invoice_or_fee','submission_confirmation','license_or_proof_received','regulator_correspondence','internal_followup','general_correspondence')",
    )
    op.drop_constraint(
        op.f("ck_classification_reviews_decision"), "classification_reviews", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_classification_reviews_decision"),
        "classification_reviews",
        "decision IN ('PENDING','IN_REVIEW','APPROVED','CORRECTED','REJECTED','RECLASSIFICATION_REQUESTED')",
    )
    op.drop_constraint(op.f("ck_licensing_tasks_status"), "licensing_tasks", type_="check")
    op.create_check_constraint(
        op.f("ck_licensing_tasks_status"),
        "licensing_tasks",
        "status IN ('OPEN','IN_REVIEW','WAITING_FOR_INFO','READY_TO_SEND','COMPLETED','CANCELLED','BLOCKED','OVERDUE')",
    )
    op.drop_constraint(op.f("ck_graph_jobs_job_type"), "graph_jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_graph_jobs_job_type"),
        "graph_jobs",
        "job_type IN ('ENSURE_SUBSCRIPTION','RENEW_SUBSCRIPTION','RECREATE_SUBSCRIPTION','SYNC_FOLDER','INGEST_EMAIL','CLASSIFY_EMAIL')",
    )
    op.create_index(
        "uq_graph_jobs_active_classify_email",
        "graph_jobs",
        ["email_id"],
        unique=True,
        postgresql_where=sa.text(
            "job_type = 'CLASSIFY_EMAIL' AND status IN ('PENDING', 'RUNNING')"
        ),
    )

    op.create_table(
        "user_principals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("user_principal_name", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("display_name", sa.Text()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        _created(),
        _updated(),
        sa.UniqueConstraint("tenant_id", "object_id", name="uq_user_principals_tenant_object"),
    )
    op.create_table(
        "user_role_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_principal_id",
            sa.Uuid(),
            sa.ForeignKey("user_principals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "roles", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "scopes", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        _created(),
    )
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_principal_id",
            sa.Uuid(),
            sa.ForeignKey("user_principals.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("timezone", sa.Text()),
        sa.Column("default_queue", sa.Text()),
        sa.Column("page_size", sa.Integer()),
        sa.Column(
            "dashboard_preferences",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "notification_preferences",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _created(),
        _updated(),
    )
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("organization_type", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        _created(),
        _updated(),
    )
    op.create_table(
        "organization_domains",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("match_subdomains", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("trust_level", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_to", sa.Date()),
        sa.Column("source", sa.Text()),
        _created(),
        _updated(),
        sa.UniqueConstraint("domain", name="uq_organization_domains_domain"),
    )
    op.create_table(
        "organization_addresses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email_address", sa.Text(), nullable=False),
        sa.Column("trust_level", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _created(),
        _updated(),
        sa.UniqueConstraint("email_address", name="uq_organization_addresses_email"),
    )
    op.create_table(
        "classification_rule_sets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_by_actor", sa.Text()),
        sa.Column("approved_by_actor", sa.Text()),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        _created(),
        sa.UniqueConstraint("name", "version", name="uq_classification_rule_sets_name_version"),
    )
    op.create_index(
        "uq_classification_rule_sets_active",
        "classification_rule_sets",
        ["name"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "classification_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "rule_set_id",
            sa.Uuid(),
            sa.ForeignKey("classification_rule_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_key", sa.Text(), nullable=False),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("conditions", postgresql.JSONB(), nullable=False),
        sa.Column("outputs", postgresql.JSONB(), nullable=False),
        sa.Column("score", sa.Numeric(5, 3), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("description", sa.Text()),
        _created(),
        _updated(),
        sa.UniqueConstraint("rule_set_id", "rule_key", name="uq_classification_rules_set_key"),
    )
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("prompt_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column(
            "model_constraints",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("input_template", sa.Text(), nullable=False),
        sa.Column("prompt_sha256", sa.Text(), nullable=False),
        sa.Column("created_by_actor", sa.Text()),
        sa.Column("approved_by_actor", sa.Text()),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        _created(),
        sa.UniqueConstraint("prompt_key", "version", name="uq_prompt_versions_key_version"),
    )
    op.create_index(
        "uq_prompt_versions_active",
        "prompt_versions",
        ["prompt_key"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.add_column("classifications", sa.Column("suggested_destination", sa.Text()))
    op.add_column("classifications", sa.Column("parent_classification_id", sa.Uuid()))
    op.add_column("classifications", sa.Column("classification_run_id", sa.Uuid()))
    op.add_column(
        "classifications",
        sa.Column("review_status", sa.Text(), server_default=sa.text("'PENDING'"), nullable=False),
    )
    op.add_column("classifications", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("classifications", sa.Column("reviewed_by_actor", sa.Text()))
    op.add_column("classifications", sa.Column("rejection_reason", sa.Text()))
    op.add_column(
        "classifications",
        sa.Column("source_revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_foreign_key(
        op.f("fk_classifications_parent_classification_id_classifications"),
        "classifications",
        "classifications",
        ["parent_classification_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "classification_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "email_id", sa.Uuid(), sa.ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "classification_id", sa.Uuid(), sa.ForeignKey("classifications.id", ondelete="SET NULL")
        ),
        sa.Column("job_id", sa.Uuid()),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column(
            "rule_set_id",
            sa.Uuid(),
            sa.ForeignKey("classification_rule_sets.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "prompt_version_id", sa.Uuid(), sa.ForeignKey("prompt_versions.id", ondelete="SET NULL")
        ),
        sa.Column("provider", sa.Text()),
        sa.Column("model", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("deterministic_output", postgresql.JSONB()),
        sa.Column("model_output", postgresql.JSONB()),
        sa.Column("merged_output", postgresql.JSONB()),
        sa.Column(
            "validation_errors",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("input_fingerprint", sa.Text(), nullable=False),
        sa.Column("prompt_fingerprint", sa.Text()),
        sa.Column("provider_request_id", sa.Text()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("estimated_cost", sa.Numeric(12, 6)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        _created(),
    )
    op.create_index(
        "ix_classification_runs_email_started", "classification_runs", ["email_id", "started_at"]
    )
    op.create_foreign_key(
        op.f("fk_classifications_classification_run_id_classification_runs"),
        "classifications",
        "classification_runs",
        ["classification_run_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.alter_column(
        "classification_reviews",
        "decision",
        server_default=sa.text("'PENDING'"),
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "classification_reviews", "reviewer_principal", existing_type=sa.Text(), nullable=True
    )
    op.alter_column(
        "classification_reviews",
        "reviewed_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.add_column("classification_reviews", sa.Column("claimed_at", sa.DateTime(timezone=True)))
    op.add_column(
        "classification_reviews", sa.Column("claim_expires_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "classification_reviews",
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column("classification_reviews", sa.Column("rejection_reason", sa.Text()))
    op.add_column("classification_reviews", sa.Column("reclassification_reason", sa.Text()))
    op.create_table(
        "classification_field_corrections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "review_id",
            sa.Uuid(),
            sa.ForeignKey("classification_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_path", sa.Text(), nullable=False),
        sa.Column("machine_value", postgresql.JSONB()),
        sa.Column("reviewed_value", postgresql.JSONB()),
        sa.Column("correction_reason", sa.Text()),
        _created(),
    )

    op.add_column("licensing_tasks", sa.Column("backup_assigned_to", sa.Text()))
    op.add_column(
        "licensing_tasks",
        sa.Column("priority", sa.Text(), server_default=sa.text("'NORMAL'"), nullable=False),
    )
    op.add_column("licensing_tasks", sa.Column("notes", sa.Text()))
    op.add_column("task_requested_items", sa.Column("category", sa.Text()))
    op.add_column(
        "task_requested_items",
        sa.Column("required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("task_requested_items", sa.Column("evidence_quote", sa.Text()))
    op.create_table(
        "task_comments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("licensing_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author_principal_id", sa.Uuid()),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("comment_type", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        _created(),
        _updated(),
    )
    op.create_index("ix_task_comments_task_created", "task_comments", ["task_id", "created_at"])
    op.create_table(
        "task_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("licensing_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("from_status", sa.Text()),
        sa.Column("to_status", sa.Text()),
        sa.Column("actor_id", sa.Text()),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_events_task_occurred", "task_events", ["task_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_task_events_task_occurred", table_name="task_events")
    op.drop_table("task_events")
    op.drop_index("ix_task_comments_task_created", table_name="task_comments")
    op.drop_table("task_comments")
    for name in ("evidence_quote", "required", "category"):
        op.drop_column("task_requested_items", name)
    for name in ("notes", "priority", "backup_assigned_to"):
        op.drop_column("licensing_tasks", name)
    op.drop_table("classification_field_corrections")
    for name in (
        "reclassification_reason",
        "rejection_reason",
        "revision",
        "claim_expires_at",
        "claimed_at",
    ):
        op.drop_column("classification_reviews", name)
    op.alter_column(
        "classification_reviews",
        "reviewed_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.alter_column(
        "classification_reviews", "reviewer_principal", existing_type=sa.Text(), nullable=False
    )
    op.drop_constraint(
        op.f("fk_classifications_classification_run_id_classification_runs"),
        "classifications",
        type_="foreignkey",
    )
    op.drop_index("ix_classification_runs_email_started", table_name="classification_runs")
    op.drop_table("classification_runs")
    op.drop_constraint(
        op.f("fk_classifications_parent_classification_id_classifications"),
        "classifications",
        type_="foreignkey",
    )
    for name in (
        "source_revision",
        "rejection_reason",
        "reviewed_by_actor",
        "reviewed_at",
        "review_status",
        "classification_run_id",
        "parent_classification_id",
        "suggested_destination",
    ):
        op.drop_column("classifications", name)
    op.drop_index("uq_prompt_versions_active", table_name="prompt_versions")
    op.drop_table("prompt_versions")
    op.drop_table("classification_rules")
    op.drop_index("uq_classification_rule_sets_active", table_name="classification_rule_sets")
    op.drop_table("classification_rule_sets")
    op.drop_table("organization_addresses")
    op.drop_table("organization_domains")
    op.drop_table("organizations")
    op.drop_table("user_preferences")
    op.drop_table("user_role_snapshots")
    op.drop_table("user_principals")
    op.drop_index("uq_graph_jobs_active_classify_email", table_name="graph_jobs")
    op.drop_constraint(op.f("ck_graph_jobs_job_type"), "graph_jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_graph_jobs_job_type"),
        "graph_jobs",
        "job_type IN ('ENSURE_SUBSCRIPTION','RENEW_SUBSCRIPTION','RECREATE_SUBSCRIPTION','SYNC_FOLDER','INGEST_EMAIL')",
    )

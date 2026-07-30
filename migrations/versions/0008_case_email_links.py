"""Correspondence links between compliance cases and mailbox threads.

Stores only identifiers, match signals, and the confirming actor. No email
body, subject, sender address, or attachment content is copied here: the
message rows remain the single source of that content.

Revision ID: 0008_case_email_links
Revises: 0007_portal_assistance
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_case_email_links"
down_revision: str | None = "0007_portal_assistance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "case_email_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "compliance_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("compliance_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.Text(), nullable=True),
        sa.Column("link_status", sa.Text(), nullable=False),
        sa.Column("match_score", sa.Numeric(4, 3), nullable=True),
        sa.Column(
            "match_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("proposed_by_actor", sa.Text(), nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by_actor", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("compliance_case_id", "email_id", name="uq_case_email_link"),
        sa.CheckConstraint(
            "link_status IN ('PROPOSED', 'CONFIRMED', 'REJECTED', 'SUPERSEDED')",
            name="ck_case_email_links_status",
        ),
    )
    op.create_index(
        "ix_case_email_links_case", "case_email_links", ["compliance_case_id", "link_status"]
    )
    op.create_index(
        "ix_case_email_links_status", "case_email_links", ["link_status", "proposed_at"]
    )
    op.create_index("ix_case_email_links_conversation", "case_email_links", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_case_email_links_conversation", table_name="case_email_links")
    op.drop_index("ix_case_email_links_status", table_name="case_email_links")
    op.drop_index("ix_case_email_links_case", table_name="case_email_links")
    op.drop_table("case_email_links")

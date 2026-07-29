"""Deadline rules, materialized deadlines, and append-only deadline history.

Each rule carries its own ``adjustment_policy`` because regulators differ on
whether a due date falling on a weekend or holiday moves. Defaulting to "shift to
the next business day" everywhere would quietly manufacture deadlines that do not
exist, so ``NONE`` is the default and any shift must be source-backed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.deadlines.enums import (
    AdjustmentPolicy,
    DeadlineEventType,
    DeadlineRuleStatus,
    DeadlineSeverity,
    DeadlineStatus,
    DeadlineType,
    RecurrenceType,
)
from app.licensing.enums import ObligationType
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, enum_check


class DeadlineRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Policy describing how a due date recurs and when work should start."""

    __tablename__ = "deadline_rules"
    __table_args__ = (
        Index("ix_deadline_rules_scope", "obligation_type", "jurisdiction_id", "license_type_id"),
        Index("ix_deadline_rules_status", "status"),
        CheckConstraint(
            "lead_time_days IS NULL OR lead_time_days >= 0",
            name="lead_time_non_negative",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="effective_range",
        ),
        enum_check("obligation_type", ObligationType, "obligation_type"),
        enum_check("recurrence_type", RecurrenceType, "recurrence_type"),
        enum_check("adjustment_policy", AdjustmentPolicy, "adjustment"),
        enum_check("status", DeadlineRuleStatus, "status"),
    )

    rule_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    obligation_type: Mapped[str] = mapped_column(nullable=False)
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jurisdictions.id", ondelete="RESTRICT")
    )
    license_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("license_types.id", ondelete="RESTRICT")
    )
    recurrence_type: Mapped[str] = mapped_column(nullable=False)
    recurrence_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: Days before the statutory date that internal preparation should begin.
    #: NULL means "use the configured default lead time".
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    adjustment_policy: Mapped[str] = mapped_column(nullable=False)
    #: Offsets for internal milestones keyed by deadline type, plus the
    #: escalation ladder. Shape is validated by app.deadlines.rules.
    escalation_policy: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    milestone_offsets: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    effective_from: Mapped[date | None]
    effective_to: Mapped[date | None]
    source_snapshot_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    status: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None]
    #: Lower wins when several rules match the same obligation.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))


class ComplianceDeadline(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A concrete dated obligation milestone.

    ``materialization_key`` makes repeated materialization runs idempotent: the
    same rule, obligation, type, and target date always resolve to one row.
    """

    __tablename__ = "compliance_deadlines"
    __table_args__ = (
        Index("ix_compliance_deadlines_due", "due_at", "status"),
        Index("ix_compliance_deadlines_obligation", "obligation_id", "deadline_type"),
        Index("ix_compliance_deadlines_case", "compliance_case_id"),
        Index("ix_compliance_deadlines_owner", "assigned_owner", "status"),
        Index(
            "uq_compliance_deadlines_materialization",
            "materialization_key",
            unique=True,
            postgresql_where=text("materialization_key IS NOT NULL"),
        ),
        enum_check("deadline_type", DeadlineType, "type"),
        enum_check("status", DeadlineStatus, "status"),
        enum_check("severity", DeadlineSeverity, "severity"),
    )

    obligation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_obligations.id", ondelete="CASCADE"), nullable=False
    )
    compliance_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("compliance_cases.id", ondelete="SET NULL")
    )
    deadline_type: Mapped[str] = mapped_column(nullable=False)
    due_at: Mapped[datetime] = mapped_column(nullable=False)
    internal_target_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(nullable=False)
    severity: Mapped[str] = mapped_column(nullable=False)
    assigned_owner: Mapped[str | None]
    backup_owner: Mapped[str | None]
    source_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deadline_rules.id", ondelete="SET NULL")
    )
    manually_overridden: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    override_reason: Mapped[str | None]
    materialization_key: Mapped[str | None]
    #: Highest escalation level already notified, so sweeps do not re-notify.
    last_escalation_level: Mapped[str | None]
    last_escalated_at: Mapped[datetime | None]
    #: Business-day adjustment actually applied, for auditability.
    applied_adjustment: Mapped[str | None]
    completed_at: Mapped[datetime | None]
    completed_by_actor: Mapped[str | None]


class DeadlineEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only record of every change to a deadline's date or state."""

    __tablename__ = "deadline_events"
    __table_args__ = (
        Index("ix_deadline_events_deadline", "deadline_id", "occurred_at"),
        enum_check("event_type", DeadlineEventType, "type"),
    )

    deadline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_deadlines.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(nullable=False)
    previous_due_at: Mapped[datetime | None]
    new_due_at: Mapped[datetime | None]
    actor_id: Mapped[str | None]
    reason: Mapped[str | None]
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)

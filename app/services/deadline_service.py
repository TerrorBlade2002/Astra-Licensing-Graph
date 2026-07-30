"""Obligation and deadline materialization, escalation, and completion."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import (
    DEADLINES_DUE_TOTAL,
    DEADLINES_OVERDUE_TOTAL,
    LICENSING_OVERDUE_OBLIGATIONS,
)
from app.deadlines.alerts import deadline_alert
from app.deadlines.calculator import classify_status, plan_deadlines
from app.deadlines.enums import (
    OPEN_DEADLINE_STATUSES,
    DeadlineEventType,
    DeadlineStatus,
    DeadlineType,
)
from app.deadlines.escalation import evaluate_escalation, resolve_recipient
from app.deadlines.recurrence import RecurrenceContext
from app.deadlines.rules import DeadlinePolicy, resolve_policy
from app.licensing.audit import add_licensing_audit, record_notification
from app.licensing.enums import ObligationStatus, ObligationType
from app.models import (
    ComplianceDeadline,
    ComplianceObligation,
    DeadlineEvent,
    DeadlineRule,
    Jurisdiction,
    LicenseBond,
    LicenseInventory,
)
from app.models.mixins import utcnow


def _to_policy(rule: DeadlineRule) -> DeadlinePolicy:
    return DeadlinePolicy(
        id=rule.id,
        rule_key=rule.rule_key,
        obligation_type=rule.obligation_type,
        recurrence_type=rule.recurrence_type,
        recurrence_config=dict(rule.recurrence_config or {}),
        adjustment_policy=rule.adjustment_policy,
        lead_time_days=rule.lead_time_days,
        milestone_offsets={k: int(v) for k, v in (rule.milestone_offsets or {}).items()},
        escalation_policy=dict(rule.escalation_policy or {}),
        jurisdiction_id=rule.jurisdiction_id,
        license_type_id=rule.license_type_id,
        effective_from=rule.effective_from,
        effective_to=rule.effective_to,
        priority=rule.priority,
    )


class DeadlineService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _active_policies(self) -> list[DeadlinePolicy]:
        rules = list(
            await self.session.scalars(select(DeadlineRule).where(DeadlineRule.status == "ACTIVE"))
        )
        return [_to_policy(rule) for rule in rules]

    async def materialize_for_obligation(
        self,
        obligation_id: uuid.UUID,
        *,
        actor: CurrentActor | None = None,
        horizon_days: int | None = None,
        commit: bool = True,
    ) -> list[ComplianceDeadline]:
        """Create any missing deadlines for one obligation.

        Idempotent: a deadline is keyed by (obligation, type, date, rule), so a
        repeated run recognises what already exists instead of duplicating.
        """
        obligation = await self.session.get(ComplianceObligation, obligation_id)
        if obligation is None:
            raise NotFoundError("Obligation not found.")

        licence = (
            await self.session.get(LicenseInventory, obligation.license_id)
            if obligation.license_id
            else None
        )
        bond = (
            await self.session.get(LicenseBond, obligation.bond_id) if obligation.bond_id else None
        )
        jurisdiction = (
            await self.session.get(Jurisdiction, obligation.jurisdiction_id)
            if obligation.jurisdiction_id
            else None
        )

        today = utcnow().date()
        horizon = horizon_days or self.settings.licensing_planning_horizon_days
        policy = resolve_policy(
            await self._active_policies(),
            obligation_type=obligation.obligation_type,
            when=today,
            jurisdiction_id=obligation.jurisdiction_id,
            license_type_id=licence.license_type_id if licence else None,
        )
        if policy is None:
            # No rule: report rather than invent a date.
            return []

        context = RecurrenceContext(
            issue_date=licence.issue_date if licence else None,
            effective_date=licence.effective_date if licence else None,
            expiration_date=licence.expiration_date if licence else None,
            regulator_supplied_due_date=obligation.statutory_due_date,
            bond_expiration_date=bond.expiration_date if bond else None,
            annual_report_date=obligation.next_due_date,
            last_completed_date=None,
        )
        statutory_type = {
            ObligationType.BOND_RENEWAL.value: DeadlineType.BOND_EXPIRY.value,
            ObligationType.ANNUAL_REPORT.value: DeadlineType.ANNUAL_REPORT_DUE.value,
        }.get(obligation.obligation_type, DeadlineType.STATUTORY_DUE.value)

        planned = plan_deadlines(
            obligation_id=obligation.id,
            obligation_type=obligation.obligation_type,
            policy=policy,
            context=context,
            horizon_start=today,
            horizon_end=today + timedelta(days=horizon),
            default_lead_days=self.settings.licensing_default_lead_days,
            timezone_name=(jurisdiction.timezone if jurisdiction else None)
            or self.settings.licensing_default_timezone,
            statutory_deadline_type=statutory_type,
            today=today,
        )
        if not planned:
            return []

        keys = [p.materialization_key for p in planned if p.materialization_key]
        existing = set(
            await self.session.scalars(
                select(ComplianceDeadline.materialization_key).where(
                    ComplianceDeadline.materialization_key.in_(keys)
                )
            )
        )

        created: list[ComplianceDeadline] = []
        for plan in planned:
            if plan.materialization_key in existing:
                continue
            deadline = ComplianceDeadline(
                obligation_id=obligation.id,
                deadline_type=plan.deadline_type,
                due_at=plan.due_at,
                internal_target_at=plan.internal_target_at,
                status=classify_status(due_at=plan.due_at),
                severity=plan.severity,
                assigned_owner=obligation.responsible_owner,
                source_rule_id=plan.source_rule_id,
                materialization_key=plan.materialization_key,
                applied_adjustment=plan.applied_adjustment,
                manually_overridden=False,
                override_reason=(
                    "; ".join(plan.notes) if plan.needs_manual_review and plan.notes else None
                ),
            )
            self.session.add(deadline)
            await self.session.flush()
            self.session.add(
                DeadlineEvent(
                    deadline_id=deadline.id,
                    event_type=DeadlineEventType.CREATED.value,
                    new_due_at=deadline.due_at,
                    actor_id=actor.actor_id if actor else "deadline-worker",
                    reason=f"Materialized from rule {policy.rule_key}.",
                    occurred_at=utcnow(),
                )
            )
            created.append(deadline)

        statutory = [p for p in planned if p.deadline_type == statutory_type]
        if statutory:
            earliest = min(statutory, key=lambda p: p.due_date)
            obligation.next_due_date = earliest.due_date
            if earliest.internal_target_at:
                obligation.internal_start_date = earliest.internal_target_at.date()
            if obligation.status == ObligationStatus.PLANNED.value:
                obligation.status = ObligationStatus.ACTIVE.value

        if created:
            add_licensing_audit(
                self.session,
                actor=actor,
                entity_type="compliance_obligation",
                entity_id=obligation.id,
                action="deadlines_materialized",
                after={"created": len(created), "rule_key": policy.rule_key},
            )
        if commit:
            await self.session.commit()
        return created

    async def materialize_all(
        self, *, actor: CurrentActor | None = None, limit: int = 500
    ) -> dict[str, int]:
        """Sweep active obligations. Safe to run repeatedly."""
        obligations = list(
            await self.session.scalars(
                select(ComplianceObligation.id)
                .where(
                    ComplianceObligation.status.in_(
                        (ObligationStatus.PLANNED.value, ObligationStatus.ACTIVE.value)
                    )
                )
                .limit(limit)
            )
        )
        created = 0
        for obligation_id in obligations:
            created += len(
                await self.materialize_for_obligation(obligation_id, actor=actor, commit=False)
            )
        await self.session.commit()
        return {"obligations": len(obligations), "deadlines_created": created}

    async def refresh_statuses(self, *, commit: bool = True) -> int:
        """Recompute APPROACHING / DUE_TODAY / OVERDUE for open deadlines."""
        deadlines = list(
            await self.session.scalars(
                select(ComplianceDeadline).where(
                    ComplianceDeadline.status.in_(OPEN_DEADLINE_STATUSES)
                )
            )
        )
        changed = 0
        for deadline in deadlines:
            fresh = classify_status(due_at=deadline.due_at)
            if fresh != deadline.status:
                deadline.status = fresh
                changed += 1
        if commit:
            await self.session.commit()
        return changed

    async def run_escalations(
        self, *, manager_actor: str | None = None, commit: bool = True
    ) -> int:
        """Notify owners as deadlines enter new escalation windows."""
        deadlines = list(
            await self.session.scalars(
                select(ComplianceDeadline).where(
                    ComplianceDeadline.status.in_(OPEN_DEADLINE_STATUSES)
                )
            )
        )
        notified = 0
        for deadline in deadlines:
            rule = (
                await self.session.get(DeadlineRule, deadline.source_rule_id)
                if deadline.source_rule_id
                else None
            )
            policy = _to_policy(rule) if rule else None
            decision = evaluate_escalation(
                due_at=deadline.due_at,
                last_escalation_level=deadline.last_escalation_level,
                ladder=policy.escalation_ladder() if policy else None,
                overdue_enabled=self.settings.deadline_overdue_escalation_enabled,
            )
            if not decision.should_notify or decision.level is None:
                continue
            recipient = resolve_recipient(
                level=decision.level,
                owner=deadline.assigned_owner,
                backup_owner=deadline.backup_owner,
                manager=manager_actor,
            )
            if not recipient:
                continue
            draft = deadline_alert(
                deadline_id=deadline.id,
                obligation_id=deadline.obligation_id,
                deadline_type=deadline.deadline_type,
                recipient_actor=recipient,
                severity=decision.severity,
                level=decision.level,
                days_remaining=decision.days_remaining,
                is_overdue=decision.is_overdue,
                window_suffix=decision.notification_key_suffix,
                compliance_case_id=deadline.compliance_case_id,
            )
            if await record_notification(self.session, draft):
                notified += 1
                deadline.last_escalation_level = decision.level
                deadline.last_escalated_at = utcnow()
                deadline.severity = decision.severity
                self.session.add(
                    DeadlineEvent(
                        deadline_id=deadline.id,
                        event_type=DeadlineEventType.ESCALATED.value,
                        actor_id="deadline-worker",
                        reason=decision.reason,
                        occurred_at=utcnow(),
                    )
                )
        if commit:
            await self.session.commit()
        return notified

    async def override_deadline(
        self,
        deadline_id: uuid.UUID,
        *,
        actor: CurrentActor,
        new_due_at: Any = None,
        assigned_owner: str | None = None,
        reason: str,
        commit: bool = True,
    ) -> ComplianceDeadline:
        deadline = await self.session.get(ComplianceDeadline, deadline_id)
        if deadline is None:
            raise NotFoundError("Deadline not found.")
        if not reason or len(reason.strip()) < 5:
            raise StateConflictError("A deadline override requires a substantive reason.")
        previous = deadline.due_at
        if new_due_at is not None:
            deadline.due_at = new_due_at
            deadline.manually_overridden = True
            deadline.status = classify_status(due_at=new_due_at)
            # Detach from the rule key so a later sweep does not "correct" it back.
            deadline.materialization_key = None
        if assigned_owner is not None:
            deadline.assigned_owner = assigned_owner
        deadline.override_reason = reason.strip()[:500]
        self.session.add(
            DeadlineEvent(
                deadline_id=deadline.id,
                event_type=(
                    DeadlineEventType.MANUALLY_OVERRIDDEN.value
                    if new_due_at is not None
                    else DeadlineEventType.OWNER_CHANGED.value
                ),
                previous_due_at=previous,
                new_due_at=deadline.due_at,
                actor_id=actor.actor_id,
                reason=reason.strip()[:500],
                occurred_at=utcnow(),
            )
        )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="compliance_deadline",
            entity_id=deadline.id,
            action="deadline_overridden",
            before={"due_at": str(previous)},
            after={"due_at": str(deadline.due_at)},
        )
        if commit:
            await self.session.commit()
        return deadline

    async def complete_deadline(
        self,
        deadline_id: uuid.UUID,
        *,
        actor: CurrentActor,
        note: str | None = None,
        commit: bool = True,
    ) -> ComplianceDeadline:
        deadline = await self.session.get(ComplianceDeadline, deadline_id)
        if deadline is None:
            raise NotFoundError("Deadline not found.")
        if deadline.status == DeadlineStatus.COMPLETED.value:
            return deadline
        deadline.status = DeadlineStatus.COMPLETED.value
        deadline.completed_at = utcnow()
        deadline.completed_by_actor = actor.actor_id
        self.session.add(
            DeadlineEvent(
                deadline_id=deadline.id,
                event_type=DeadlineEventType.COMPLETED.value,
                actor_id=actor.actor_id,
                reason=note,
                occurred_at=utcnow(),
            )
        )
        if commit:
            await self.session.commit()
        return deadline

    async def calendar(
        self,
        *,
        start: date,
        end: date,
        legal_entity_id: uuid.UUID | None = None,
        owner: str | None = None,
        obligation_type: str | None = None,
        include_completed: bool = False,
    ) -> list[dict[str, Any]]:
        """Calendar rows joining deadlines to their obligation context."""
        stmt = (
            select(ComplianceDeadline, ComplianceObligation)
            .join(
                ComplianceObligation,
                ComplianceObligation.id == ComplianceDeadline.obligation_id,
            )
            .where(
                func.date(ComplianceDeadline.due_at) >= start,
                func.date(ComplianceDeadline.due_at) <= end,
            )
            .order_by(ComplianceDeadline.due_at)
        )
        if not include_completed:
            stmt = stmt.where(ComplianceDeadline.status.in_(OPEN_DEADLINE_STATUSES))
        if legal_entity_id:
            stmt = stmt.where(ComplianceObligation.legal_entity_id == legal_entity_id)
        if owner:
            stmt = stmt.where(ComplianceDeadline.assigned_owner == owner)
        if obligation_type:
            stmt = stmt.where(ComplianceObligation.obligation_type == obligation_type)

        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "deadline_id": str(deadline.id),
                "obligation_id": str(obligation.id),
                "compliance_case_id": (
                    str(deadline.compliance_case_id) if deadline.compliance_case_id else None
                ),
                "legal_entity_id": str(obligation.legal_entity_id),
                "jurisdiction_id": (
                    str(obligation.jurisdiction_id) if obligation.jurisdiction_id else None
                ),
                "obligation_type": obligation.obligation_type,
                "title": obligation.title,
                "deadline_type": deadline.deadline_type,
                "due_at": deadline.due_at.isoformat(),
                "internal_target_at": (
                    deadline.internal_target_at.isoformat() if deadline.internal_target_at else None
                ),
                "status": deadline.status,
                "severity": deadline.severity,
                "assigned_owner": deadline.assigned_owner,
                "manually_overridden": deadline.manually_overridden,
                "escalation_level": deadline.last_escalation_level,
                "is_statutory": deadline.deadline_type
                in (
                    DeadlineType.STATUTORY_DUE.value,
                    DeadlineType.BOND_EXPIRY.value,
                    DeadlineType.ANNUAL_REPORT_DUE.value,
                ),
            }
            for deadline, obligation in rows
        ]

    async def refresh_metrics(self) -> None:
        rows = (
            await self.session.execute(
                select(
                    ComplianceDeadline.deadline_type,
                    ComplianceDeadline.status,
                    func.count(),
                )
                .where(ComplianceDeadline.status.in_(OPEN_DEADLINE_STATUSES))
                .group_by(ComplianceDeadline.deadline_type, ComplianceDeadline.status)
            )
        ).all()
        due: dict[str, int] = {}
        overdue: dict[str, int] = {}
        for deadline_type, status, count in rows:
            due[deadline_type] = due.get(deadline_type, 0) + int(count)
            if status == DeadlineStatus.OVERDUE.value:
                overdue[deadline_type] = overdue.get(deadline_type, 0) + int(count)
        for deadline_type, count in due.items():
            DEADLINES_DUE_TOTAL.labels(deadline_type=deadline_type).set(count)
        for deadline_type, count in overdue.items():
            DEADLINES_OVERDUE_TOTAL.labels(deadline_type=deadline_type).set(count)
        overdue_obligations = (
            await self.session.scalar(
                select(func.count())
                .select_from(ComplianceObligation)
                .where(
                    ComplianceObligation.status == ObligationStatus.ACTIVE.value,
                    ComplianceObligation.next_due_date < utcnow().date(),
                )
            )
            or 0
        )
        LICENSING_OVERDUE_OBLIGATIONS.set(overdue_obligations)

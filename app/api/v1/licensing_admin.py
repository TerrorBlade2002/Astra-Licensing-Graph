"""Governed requirement-rule and deadline-policy administration."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.dependencies import ActorDep, SessionDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.core.exceptions import NotFoundError, StateConflictError
from app.deadlines.enums import AdjustmentPolicy, EscalationLevel
from app.deadlines.rules import validate_milestone_offsets, validate_recurrence_config
from app.licensing.audit import add_licensing_audit
from app.licensing.enums import ObligationType
from app.models import (
    DeadlineRule,
    RequirementRule,
    RequirementRuleSet,
    RequirementRuleSource,
    RequirementSourceSnapshot,
)
from app.models.mixins import utcnow
from app.requirements.rules import Rule

router = APIRouter(tags=["licensing-admin"])

AdminDep = Annotated[CurrentActor, Depends(require_role(Role.ADMIN))]
ManagerDep = Annotated[CurrentActor, Depends(require_role(Role.MANAGER))]


class RuleSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    derived_from_rule_set_id: uuid.UUID | None = None


class RequirementRuleCreate(BaseModel):
    rule_key: str = Field(min_length=1, max_length=160)
    jurisdiction_id: uuid.UUID | None = None
    license_type_id: uuid.UUID | None = None
    conditions: dict[str, Any]
    outcome: str
    explanation_template: str
    priority: int = 100
    filing_channels: list[str] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    source_snapshot_ids: list[uuid.UUID] = Field(min_length=1)
    effective_from: date | None = None
    effective_to: date | None = None
    requires_counsel_review: bool = False
    enabled: bool = True
    notes: str | None = None


class DeadlineRuleCreate(BaseModel):
    rule_key: str = Field(min_length=1, max_length=160)
    obligation_type: str
    jurisdiction_id: uuid.UUID | None = None
    license_type_id: uuid.UUID | None = None
    recurrence_type: str
    recurrence_config: dict[str, Any] = Field(default_factory=dict)
    lead_time_days: int | None = Field(default=None, ge=0)
    adjustment_policy: str = "NONE"
    escalation_policy: dict[str, Any] = Field(default_factory=dict)
    milestone_offsets: dict[str, Any] = Field(default_factory=dict)
    effective_from: date | None = None
    effective_to: date | None = None
    source_snapshot_ids: list[uuid.UUID] = Field(min_length=1)
    description: str | None = None
    priority: int = 100


async def _approved_snapshots(
    session: SessionDep, snapshot_ids: list[uuid.UUID]
) -> list[RequirementSourceSnapshot]:
    rows = list(
        await session.scalars(
            select(RequirementSourceSnapshot).where(
                RequirementSourceSnapshot.id.in_(snapshot_ids),
                RequirementSourceSnapshot.review_status.in_(("APPROVED", "SUPERSEDED")),
            )
        )
    )
    if len({row.id for row in rows}) != len(set(snapshot_ids)):
        raise StateConflictError(
            "Every rule citation must reference an approved requirement-source snapshot."
        )
    return rows


@router.get("/requirement-rule-sets")
async def list_rule_sets(session: SessionDep, actor: ActorDep) -> list[dict[str, object]]:
    rows = list(
        await session.scalars(
            select(RequirementRuleSet).order_by(
                RequirementRuleSet.name, RequirementRuleSet.version.desc()
            )
        )
    )
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "version": row.version,
            "status": row.status,
            "description": row.description,
            "activated_at": row.activated_at.isoformat() if row.activated_at else None,
        }
        for row in rows
    ]


@router.post("/requirement-rule-sets", status_code=201)
async def create_rule_set(
    payload: RuleSetCreate, session: SessionDep, actor: AdminDep
) -> dict[str, object]:
    highest = (
        await session.scalar(
            select(func.max(RequirementRuleSet.version)).where(
                RequirementRuleSet.name == payload.name
            )
        )
        or 0
    )
    row = RequirementRuleSet(
        name=payload.name,
        version=highest + 1,
        status="DRAFT",
        description=payload.description,
        derived_from_rule_set_id=payload.derived_from_rule_set_id,
    )
    session.add(row)
    await session.commit()
    return {"id": str(row.id), "name": row.name, "version": row.version, "status": row.status}


@router.post("/requirement-rule-sets/{rule_set_id}/rules", status_code=201)
async def create_requirement_rule(
    rule_set_id: uuid.UUID,
    payload: RequirementRuleCreate,
    session: SessionDep,
    actor: AdminDep,
) -> dict[str, object]:
    rule_set = await session.get(RequirementRuleSet, rule_set_id)
    if rule_set is None:
        raise NotFoundError("Requirement rule set not found.")
    if rule_set.status != "DRAFT":
        raise StateConflictError("Rules can only be added to a DRAFT rule set.")
    await _approved_snapshots(session, payload.source_snapshot_ids)
    pure = Rule(
        id=uuid.uuid4(),
        rule_key=payload.rule_key,
        jurisdiction_id=payload.jurisdiction_id,
        license_type_id=payload.license_type_id,
        conditions=payload.conditions,
        outcome=payload.outcome,
        explanation_template=payload.explanation_template,
        priority=payload.priority,
        filing_channels=tuple(payload.filing_channels),
        required_facts=tuple(payload.required_facts),
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        requires_counsel_review=payload.requires_counsel_review,
        enabled=payload.enabled,
    )
    pure.validate()
    row = RequirementRule(
        rule_set_id=rule_set.id,
        **payload.model_dump(exclude={"source_snapshot_ids"}),
    )
    session.add(row)
    await session.flush()
    for index, snapshot_id in enumerate(payload.source_snapshot_ids):
        session.add(
            RequirementRuleSource(
                requirement_rule_id=row.id,
                requirement_source_snapshot_id=snapshot_id,
                is_primary=index == 0,
            )
        )
    await session.commit()
    return {"id": str(row.id), "rule_key": row.rule_key}


@router.post("/requirement-rule-sets/{rule_set_id}/activate")
async def activate_rule_set(
    rule_set_id: uuid.UUID, session: SessionDep, actor: ManagerDep
) -> dict[str, object]:
    rule_set = await session.get(RequirementRuleSet, rule_set_id)
    if rule_set is None:
        raise NotFoundError("Requirement rule set not found.")
    rules = list(
        await session.scalars(
            select(RequirementRule).where(
                RequirementRule.rule_set_id == rule_set.id,
                RequirementRule.enabled.is_(True),
            )
        )
    )
    if not rules:
        raise StateConflictError("An active rule set must contain at least one enabled rule.")
    for rule in rules:
        links = list(
            await session.scalars(
                select(RequirementRuleSource).where(
                    RequirementRuleSource.requirement_rule_id == rule.id
                )
            )
        )
        if not links:
            raise StateConflictError(f"Rule {rule.rule_key!r} has no source provenance.")
        await _approved_snapshots(session, [link.requirement_source_snapshot_id for link in links])
    previous = list(
        await session.scalars(
            select(RequirementRuleSet).where(
                RequirementRuleSet.name == rule_set.name,
                RequirementRuleSet.status == "ACTIVE",
                RequirementRuleSet.id != rule_set.id,
            )
        )
    )
    for row in previous:
        row.status = "RETIRED"
        row.retired_at = utcnow()
    rule_set.status = "ACTIVE"
    rule_set.approved_by_actor = actor.actor_id
    rule_set.activated_at = utcnow()
    add_licensing_audit(
        session,
        actor=actor,
        entity_type="requirement_rule_set",
        entity_id=rule_set.id,
        action="requirement_rule_set_activated",
        after={"name": rule_set.name, "version": rule_set.version},
    )
    await session.commit()
    return {"id": str(rule_set.id), "status": rule_set.status}


@router.get("/deadline-rules")
async def list_deadline_rules(session: SessionDep, actor: ActorDep) -> list[dict[str, object]]:
    rows = list(await session.scalars(select(DeadlineRule).order_by(DeadlineRule.rule_key)))
    return [
        {
            "id": str(row.id),
            "rule_key": row.rule_key,
            "obligation_type": row.obligation_type,
            "recurrence_type": row.recurrence_type,
            "lead_time_days": row.lead_time_days,
            "adjustment_policy": row.adjustment_policy,
            "status": row.status,
            "source_snapshot_ids": [str(value) for value in row.source_snapshot_ids],
        }
        for row in rows
    ]


@router.post("/deadline-rules", status_code=201)
async def create_deadline_rule(
    payload: DeadlineRuleCreate, session: SessionDep, actor: AdminDep
) -> dict[str, object]:
    await _approved_snapshots(session, payload.source_snapshot_ids)
    validate_recurrence_config(payload.recurrence_type, payload.recurrence_config)
    validate_milestone_offsets(payload.milestone_offsets)
    if payload.obligation_type not in {item.value for item in ObligationType}:
        raise StateConflictError("The deadline rule has an unknown obligation type.")
    if payload.adjustment_policy not in {item.value for item in AdjustmentPolicy}:
        raise StateConflictError("The deadline rule has an unknown adjustment policy.")
    ladder = payload.escalation_policy.get("ladder", {})
    if not isinstance(ladder, dict) or any(
        str(level) not in {item.value for item in EscalationLevel} for level in ladder.values()
    ):
        raise StateConflictError("The escalation ladder contains an unknown role level.")
    row = DeadlineRule(status="DRAFT", **payload.model_dump())
    session.add(row)
    await session.commit()
    return {"id": str(row.id), "rule_key": row.rule_key, "status": row.status}


@router.post("/deadline-rules/{rule_id}/activate")
async def activate_deadline_rule(
    rule_id: uuid.UUID, session: SessionDep, actor: ManagerDep
) -> dict[str, object]:
    rule = await session.get(DeadlineRule, rule_id)
    if rule is None:
        raise NotFoundError("Deadline rule not found.")
    await _approved_snapshots(session, list(rule.source_snapshot_ids))
    rule.status = "ACTIVE"
    add_licensing_audit(
        session,
        actor=actor,
        entity_type="deadline_rule",
        entity_id=rule.id,
        action="deadline_rule_activated",
        after={"rule_key": rule.rule_key},
    )
    await session.commit()
    return {"id": str(rule.id), "status": rule.status}

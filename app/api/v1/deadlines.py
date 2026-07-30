"""Deadline materialization, override, escalation, and calendar endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.models import ComplianceDeadline
from app.schemas.licensing import (
    CalendarEntryOut,
    DeadlineComplete,
    DeadlineOut,
    DeadlineUpdate,
    MaterializeRequest,
)
from app.services.deadline_service import DeadlineService

router = APIRouter(tags=["deadlines"])

AnalystDep = Annotated[CurrentActor, Depends(require_role(Role.ANALYST))]
ManagerDep = Annotated[CurrentActor, Depends(require_role(Role.MANAGER))]


@router.get("/deadlines", response_model=list[DeadlineOut])
async def list_deadlines(
    session: SessionDep,
    actor: ActorDep,
    status: str | None = None,
    assigned_owner: str | None = None,
    due_before: datetime | None = None,
) -> list[ComplianceDeadline]:
    stmt = select(ComplianceDeadline).order_by(ComplianceDeadline.due_at)
    if status:
        stmt = stmt.where(ComplianceDeadline.status == status)
    if assigned_owner:
        stmt = stmt.where(ComplianceDeadline.assigned_owner == assigned_owner)
    if due_before:
        stmt = stmt.where(ComplianceDeadline.due_at <= due_before)
    return list(await session.scalars(stmt))


@router.post("/deadlines/materialize")
async def materialize(
    payload: MaterializeRequest,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> dict[str, int]:
    service = DeadlineService(session, settings)
    if payload.obligation_id:
        rows = await service.materialize_for_obligation(
            payload.obligation_id,
            actor=actor,
            horizon_days=payload.horizon_days,
        )
        return {"materialized": len(rows)}
    result = await service.materialize_all(actor=actor)
    return {"materialized": result["deadlines_created"]}


@router.patch("/deadlines/{deadline_id}", response_model=DeadlineOut)
async def override_deadline(
    deadline_id: uuid.UUID,
    payload: DeadlineUpdate,
    session: SessionDep,
    settings: SettingsDep,
    actor: ManagerDep,
) -> ComplianceDeadline:
    return await DeadlineService(session, settings).override_deadline(
        deadline_id, actor=actor, **payload.model_dump(exclude_none=True)
    )


@router.post("/deadlines/{deadline_id}/complete", response_model=DeadlineOut)
async def complete_deadline(
    deadline_id: uuid.UUID,
    payload: DeadlineComplete,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> ComplianceDeadline:
    return await DeadlineService(session, settings).complete_deadline(
        deadline_id, actor=actor, note=payload.note
    )


@router.post("/deadlines/escalate")
async def escalate(session: SessionDep, settings: SettingsDep, actor: ManagerDep) -> dict[str, int]:
    return {"notifications": await DeadlineService(session, settings).run_escalations()}


@router.get("/calendar", response_model=list[CalendarEntryOut])
async def calendar(
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
    start_at: date | None = None,
    end_at: date | None = None,
    legal_entity_id: uuid.UUID | None = None,
    owner: str | None = None,
) -> list[dict[str, object]]:
    start = start_at or date.today()
    end = end_at or (start + timedelta(days=settings.licensing_planning_horizon_days))
    return await DeadlineService(session, settings).calendar(
        start=start,
        end=end,
        legal_entity_id=legal_entity_id,
        owner=owner,
    )

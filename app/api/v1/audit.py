"""Audit-event endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import SessionDep
from app.repositories.events import EventRepository
from app.schemas.common import Page, PageParams
from app.schemas.event import AuditEventOut

router = APIRouter(tags=["audit"])


@router.get("/audit-events", response_model=Page[AuditEventOut])
async def list_audit_events(
    session: SessionDep,
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[str | None, Query()] = None,
    actor_id: Annotated[str | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    occurred_from: Annotated[datetime | None, Query()] = None,
    occurred_to: Annotated[datetime | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[AuditEventOut]:
    params = PageParams(page=page, page_size=page_size)
    rows, total = await EventRepository(session).list_audit_events(
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        offset=params.offset,
        limit=params.page_size,
    )
    # AuditEventOut deliberately omits before_data/after_data free-form blobs
    # and any secret-bearing fields; metadata passes through the redaction
    # policy applied at write time.
    return Page(
        items=[AuditEventOut.model_validate(r) for r in rows],
        page=params.page,
        page_size=params.page_size,
        total=total,
    )

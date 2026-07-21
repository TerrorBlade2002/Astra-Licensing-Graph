"""Email endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import SessionDep
from app.core.exceptions import NotFoundError
from app.repositories.emails import EmailRepository
from app.repositories.events import EventRepository
from app.schemas.common import Page, PageParams
from app.schemas.email import EmailDetailOut, EmailListFilters, EmailListItemOut
from app.schemas.event import EmailProcessingEventOut
from app.services import task_queries

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("", response_model=Page[EmailListItemOut])
async def list_emails(
    session: SessionDep,
    mailbox_id: Annotated[uuid.UUID | None, Query()] = None,
    processing_state: Annotated[str | None, Query()] = None,
    sender_email: Annotated[str | None, Query()] = None,
    received_from: Annotated[datetime | None, Query()] = None,
    received_to: Annotated[datetime | None, Query()] = None,
    has_attachments: Annotated[bool | None, Query()] = None,
    subject_contains: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[EmailListItemOut]:
    filters = EmailListFilters(
        mailbox_id=mailbox_id,
        processing_state=processing_state,
        sender_email=sender_email,
        received_from=received_from,
        received_to=received_to,
        has_attachments=has_attachments,
        subject_contains=subject_contains,
    )
    return await task_queries.list_emails(
        session, filters, PageParams(page=page, page_size=page_size)
    )


@router.get("/{email_id}", response_model=EmailDetailOut, response_model_exclude_none=False)
async def get_email(
    email_id: uuid.UUID,
    session: SessionDep,
    include_body: Annotated[bool, Query()] = False,
) -> EmailDetailOut:
    return await task_queries.get_email_detail(session, email_id, include_body=include_body)


@router.get("/{email_id}/events", response_model=list[EmailProcessingEventOut])
async def list_email_events(
    email_id: uuid.UUID, session: SessionDep
) -> list[EmailProcessingEventOut]:
    email = await EmailRepository(session).get(email_id)
    if email is None:
        raise NotFoundError(f"Email {email_id} not found.", details={"email_id": str(email_id)})
    events = await EventRepository(session).list_for_email(email_id)
    return [EmailProcessingEventOut.model_validate(e) for e in events]

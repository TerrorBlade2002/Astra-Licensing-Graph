"""Mailbox endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.dependencies import SessionDep
from app.core.exceptions import NotFoundError
from app.repositories.mailboxes import MailboxRepository
from app.schemas.mailbox import MailboxFolderOut, MailboxOut

router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])


@router.get("", response_model=list[MailboxOut])
async def list_mailboxes(session: SessionDep) -> list[MailboxOut]:
    mailboxes = await MailboxRepository(session).list_all()
    return [MailboxOut.model_validate(m) for m in mailboxes]


@router.get("/{mailbox_id}", response_model=MailboxOut)
async def get_mailbox(mailbox_id: uuid.UUID, session: SessionDep) -> MailboxOut:
    mailbox = await MailboxRepository(session).get(mailbox_id)
    if mailbox is None:
        raise NotFoundError(
            f"Mailbox {mailbox_id} not found.", details={"mailbox_id": str(mailbox_id)}
        )
    return MailboxOut.model_validate(mailbox)


@router.get("/{mailbox_id}/folders", response_model=list[MailboxFolderOut])
async def list_mailbox_folders(
    mailbox_id: uuid.UUID, session: SessionDep
) -> list[MailboxFolderOut]:
    repo = MailboxRepository(session)
    if await repo.get(mailbox_id) is None:
        raise NotFoundError(
            f"Mailbox {mailbox_id} not found.", details={"mailbox_id": str(mailbox_id)}
        )
    folders = await repo.list_folders(mailbox_id)
    return [MailboxFolderOut.model_validate(f) for f in folders]

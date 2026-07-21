"""Mailbox and folder data access."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models import Mailbox, MailboxFolder
from app.repositories.base import BaseRepository


class MailboxRepository(BaseRepository):
    async def list_all(self) -> list[Mailbox]:
        result = await self.session.scalars(select(Mailbox).order_by(Mailbox.address))
        return list(result)

    async def get(self, mailbox_id: uuid.UUID) -> Mailbox | None:
        return await self.session.get(Mailbox, mailbox_id)

    async def get_by_address(self, address: str) -> Mailbox | None:
        normalized = address.strip().lower()
        result = await self.session.scalars(
            select(Mailbox).where(func.lower(Mailbox.address) == normalized)
        )
        return result.first()

    async def create(
        self,
        *,
        address: str,
        display_name: str | None = None,
        graph_user_id: str | None = None,
    ) -> Mailbox:
        mailbox = Mailbox(
            address=address.strip().lower(),
            display_name=display_name,
            graph_user_id=graph_user_id,
        )
        self.session.add(mailbox)
        await self.session.flush()
        return mailbox

    async def list_folders(self, mailbox_id: uuid.UUID) -> list[MailboxFolder]:
        result = await self.session.scalars(
            select(MailboxFolder)
            .where(MailboxFolder.mailbox_id == mailbox_id)
            .order_by(MailboxFolder.display_name)
        )
        return list(result)

    async def get_folder_by_graph_id(
        self, mailbox_id: uuid.UUID, graph_folder_id: str
    ) -> MailboxFolder | None:
        result = await self.session.scalars(
            select(MailboxFolder).where(
                MailboxFolder.mailbox_id == mailbox_id,
                MailboxFolder.graph_folder_id == graph_folder_id,
            )
        )
        return result.first()

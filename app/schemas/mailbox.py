"""Mailbox API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.common import ORMModel


class MailboxOut(ORMModel):
    id: uuid.UUID
    address: str
    display_name: str | None
    graph_user_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MailboxFolderOut(ORMModel):
    id: uuid.UUID
    mailbox_id: uuid.UUID
    graph_folder_id: str
    parent_graph_folder_id: str | None
    display_name: str
    folder_path: str | None
    purpose: str | None
    is_hidden: bool
    last_verified_at: datetime | None

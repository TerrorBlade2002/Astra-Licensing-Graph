"""Email data access with filtered, stable pagination."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from app.models import Classification, ClassificationReview, Email, LicensingTask
from app.repositories.base import BaseRepository
from app.schemas.email import EmailListFilters


class EmailRepository(BaseRepository):
    def _apply_filters(
        self, stmt: Select[tuple[Email]], filters: EmailListFilters
    ) -> Select[tuple[Email]]:
        if filters.mailbox_id is not None:
            stmt = stmt.where(Email.mailbox_id == filters.mailbox_id)
        if filters.processing_state is not None:
            stmt = stmt.where(Email.processing_state == filters.processing_state)
        if filters.sender_email is not None:
            stmt = stmt.where(func.lower(Email.sender_email) == filters.sender_email)
        if filters.received_from is not None:
            stmt = stmt.where(Email.received_at >= filters.received_from)
        if filters.received_to is not None:
            stmt = stmt.where(Email.received_at <= filters.received_to)
        if filters.has_attachments is not None:
            stmt = stmt.where(Email.has_attachments == filters.has_attachments)
        if filters.subject_contains is not None:
            stmt = stmt.where(Email.subject.ilike(f"%{filters.subject_contains}%"))
        return stmt

    async def list_paginated(
        self, filters: EmailListFilters, *, offset: int, limit: int
    ) -> tuple[list[Email], int]:
        base = self._apply_filters(select(Email), filters)
        total = await self.session.scalar(
            base.with_only_columns(func.count(Email.id)).order_by(None)
        )
        # Stable ordering: received_at DESC with id as the deterministic tiebreaker.
        rows = await self.session.scalars(
            base.order_by(Email.received_at.desc().nulls_last(), Email.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(rows), int(total or 0)

    async def get(self, email_id: uuid.UUID) -> Email | None:
        return await self.session.get(Email, email_id)

    async def get_with_relations(self, email_id: uuid.UUID) -> Email | None:
        stmt = (
            select(Email)
            .where(Email.id == email_id)
            .options(
                selectinload(Email.recipients),
                selectinload(Email.attachments),
                selectinload(Email.tasks),
            )
        )
        result = await self.session.scalars(stmt)
        return result.first()

    async def get_current_classification(self, email_id: uuid.UUID) -> Classification | None:
        result = await self.session.scalars(
            select(Classification).where(
                Classification.email_id == email_id,
                Classification.is_current.is_(True),
            )
        )
        return result.first()

    async def get_latest_review(self, email_id: uuid.UUID) -> ClassificationReview | None:
        result = await self.session.scalars(
            select(ClassificationReview)
            .join(Classification, ClassificationReview.classification_id == Classification.id)
            .where(Classification.email_id == email_id)
            .order_by(ClassificationReview.reviewed_at.desc())
        )
        return result.first()

    async def get_task(self, email_id: uuid.UUID) -> LicensingTask | None:
        result = await self.session.scalars(
            select(LicensingTask)
            .where(LicensingTask.email_id == email_id)
            .order_by(LicensingTask.created_at.desc())
        )
        return result.first()

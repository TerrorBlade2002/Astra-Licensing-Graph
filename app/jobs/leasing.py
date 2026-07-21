"""Leases and cross-replica scheduler exclusion."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MailboxSyncState
from app.models.mixins import utcnow

# Arbitrary but stable key for the single periodic scheduler.
SCHEDULER_ADVISORY_LOCK_KEY = 0x5A57_2A01


async def try_acquire_scheduler_lock(session: AsyncSession) -> bool:
    """Session-scoped PostgreSQL advisory lock; holds while the session lives."""
    result = await session.execute(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": SCHEDULER_ADVISORY_LOCK_KEY}
    )
    return bool(result.scalar())


async def release_scheduler_lock(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT pg_advisory_unlock(:key)"), {"key": SCHEDULER_ADVISORY_LOCK_KEY}
    )


async def acquire_sync_lease(
    session: AsyncSession,
    sync_state_id: uuid.UUID,
    *,
    owner: str,
    lease_seconds: int,
) -> bool:
    """Acquire the per-folder sync lease; free or expired leases are claimable.

    Commits on success so the lease is visible to other workers immediately.
    """
    now = utcnow()
    result = await session.execute(
        update(MailboxSyncState)
        .where(
            MailboxSyncState.id == sync_state_id,
            (MailboxSyncState.lease_owner.is_(None))
            | (MailboxSyncState.lease_expires_at < now)
            | (MailboxSyncState.lease_owner == owner),
        )
        .values(lease_owner=owner, lease_expires_at=now + timedelta(seconds=lease_seconds))
    )
    await session.commit()
    return bool(getattr(result, "rowcount", 0))


async def release_sync_lease(
    session: AsyncSession, sync_state_id: uuid.UUID, *, owner: str
) -> None:
    await session.execute(
        update(MailboxSyncState)
        .where(MailboxSyncState.id == sync_state_id, MailboxSyncState.lease_owner == owner)
        .values(lease_owner=None, lease_expires_at=None)
    )
    await session.commit()


async def get_sync_state(
    session: AsyncSession, sync_state_id: uuid.UUID
) -> MailboxSyncState | None:
    state: MailboxSyncState | None = await session.scalar(
        select(MailboxSyncState).where(MailboxSyncState.id == sync_state_id)
    )
    return state

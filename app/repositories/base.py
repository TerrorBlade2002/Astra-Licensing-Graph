"""Repository base: thin data-access wrappers around an AsyncSession.

Repositories perform reads and writes; they never decide workflow transitions
or own transaction boundaries — services do.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

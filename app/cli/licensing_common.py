"""Shared runtime helpers for Milestone 6 operator CLIs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.domain.enums import ActorType


def operator_actor(actor_id: str) -> CurrentActor:
    return CurrentActor(
        actor_type=ActorType.HUMAN,
        actor_id=actor_id,
        tenant_id="operator-cli",
        object_id=actor_id,
        display_name=actor_id,
        roles=("Licensing.Admin", "Licensing.Manager", "Licensing.Reviewer"),
        scopes=(),
    )


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            yield session
    finally:
        await engine.dispose()

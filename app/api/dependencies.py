"""FastAPI dependencies: settings, database sessions, current actor."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.enums import ActorType
from app.services.email_state import Actor


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


async def get_db_session(
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    # One AsyncSession per request; never shared across concurrent tasks.
    async with session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


async def get_current_actor(
    settings: SettingsDep,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
) -> Actor:
    """CurrentActor abstraction.

    Milestone 1 ships read-only endpoints, so this is a placeholder boundary:
    AUTH_MODE=development accepts a synthetic actor from a controlled header
    (already rejected at startup when APP_ENV=production). Microsoft Entra JWT
    validation replaces the 'entra' branch before any portal exposure.
    """
    if settings.auth_mode == "development":
        actor_id = (x_actor_id or "dev-user").strip()[:200]
        return Actor(actor_type=ActorType.HUMAN, actor_id=actor_id)
    raise HTTPException(
        status_code=501,
        detail="Entra JWT authentication is not implemented in Milestone 1.",
    )


ActorDep = Annotated[Actor, Depends(get_current_actor)]

"""FastAPI dependencies: settings, database sessions, current actor."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.actors import CurrentActor
from app.auth.tokens import EntraTokenValidator
from app.core.config import Settings
from app.domain.enums import ActorType
from app.graph.auth import MsalConfidentialClientTokenProvider
from app.graph.client import GraphHttpClient
from app.models import UserPrincipal, UserRoleSnapshot
from app.models.mixins import utcnow


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


async def get_graph_client(settings: SettingsDep) -> AsyncIterator[GraphHttpClient]:
    client = GraphHttpClient(settings, MsalConfidentialClientTokenProvider(settings))
    try:
        yield client
    finally:
        await client.aclose()


GraphClientDep = Annotated[GraphHttpClient, Depends(get_graph_client)]


async def get_current_actor(
    settings: SettingsDep,
    session: SessionDep,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    x_actor_roles: Annotated[str | None, Header(alias="X-Actor-Roles")] = None,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
    ] = None,
) -> CurrentActor:
    if settings.auth_mode == "development":
        if settings.app_env not in ("local", "test"):
            raise HTTPException(status_code=503, detail="Development actor mode is disabled.")
        actor_id = (x_actor_id or "dev-user").strip()[:200]
        roles = tuple(
            value.strip()
            for value in (x_actor_roles or "Licensing.Admin").split(",")
            if value.strip()
        )
        return CurrentActor(
            actor_type=ActorType.HUMAN,
            actor_id=actor_id,
            tenant_id="development",
            object_id=actor_id,
            display_name=actor_id,
            principal_name=actor_id,
            roles=roles,
            scopes=(settings.entra_api_scope,),
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="A bearer access token is required.")
    try:
        claims = await EntraTokenValidator(settings).validate(credentials.credentials)
    except Exception as exc:
        raise HTTPException(
            status_code=401, detail="Bearer access token validation failed."
        ) from exc
    now = utcnow()
    tenant_id, object_id = str(claims["tid"]), str(claims["oid"])
    principal = (
        await session.scalars(
            select(UserPrincipal).where(
                UserPrincipal.tenant_id == tenant_id, UserPrincipal.object_id == object_id
            )
        )
    ).first()
    if principal is None:
        principal = UserPrincipal(
            tenant_id=tenant_id, object_id=object_id, first_seen_at=now, last_seen_at=now
        )
        session.add(principal)
    principal.user_principal_name = claims.get("preferred_username")
    principal.email = claims.get("email")
    principal.display_name = claims.get("name")
    principal.last_seen_at = now
    roles = tuple(str(value) for value in claims.get("roles", []))
    scopes = tuple(str(claims.get("scp", "")).split())
    await session.flush()
    session.add(
        UserRoleSnapshot(
            user_principal_id=principal.id,
            roles=list(roles),
            scopes=list(scopes),
            source="entra_access_token",
            observed_at=now,
        )
    )
    await session.commit()
    return CurrentActor(
        actor_type=ActorType.HUMAN,
        actor_id=object_id,
        tenant_id=tenant_id,
        object_id=object_id,
        display_name=principal.display_name,
        principal_name=principal.user_principal_name or principal.email,
        roles=roles,
        scopes=scopes,
    )


ActorDep = Annotated[CurrentActor, Depends(get_current_actor)]

"""FastAPI role-policy dependencies; backend authorization is authoritative."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException

from app.auth.actors import CurrentActor
from app.auth.roles import Role, has_any_role, has_role


def require_role(required: Role) -> Callable[..., Awaitable[CurrentActor]]:
    from app.api.dependencies import get_current_actor

    async def dependency(
        actor: Annotated[CurrentActor, Depends(get_current_actor)],
    ) -> CurrentActor:
        if not has_role(actor.roles, required):
            raise HTTPException(status_code=403, detail=f"{required.value} role required.")
        return actor

    return dependency


def require_any_role(*required: Role) -> Callable[..., Awaitable[CurrentActor]]:
    """Allow access when the actor holds any one of several distinct authorities.

    Needed where a seniority ladder cannot express the rule — for example an
    information request may be answered by its assigned owner *or* by a manager
    acting on their behalf.
    """
    from app.api.dependencies import get_current_actor

    async def dependency(
        actor: Annotated[CurrentActor, Depends(get_current_actor)],
    ) -> CurrentActor:
        if not has_any_role(actor.roles, required):
            names = " or ".join(role.value for role in required)
            raise HTTPException(status_code=403, detail=f"{names} role required.")
        return actor

    return dependency

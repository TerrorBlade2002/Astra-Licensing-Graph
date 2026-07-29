"""FastAPI role-policy dependencies; backend authorization is authoritative."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException

from app.auth.actors import CurrentActor
from app.auth.roles import Role, has_role


def require_role(required: Role) -> Callable[..., Awaitable[CurrentActor]]:
    from app.api.dependencies import get_current_actor

    async def dependency(
        actor: Annotated[CurrentActor, Depends(get_current_actor)],
    ) -> CurrentActor:
        if not has_role(actor.roles, required):
            raise HTTPException(status_code=403, detail=f"{required.value} role required.")
        return actor

    return dependency

"""Operations status for the deployed environment.

One read-only endpoint that answers "is the deployment healthy?" using data the
application already records. It is intentionally not an operations platform:
there is no incident state, no acknowledgement workflow, and no storage.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.services.operations_status_service import OperationsStatusService

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/status")
async def operations_status(
    session: SessionDep, settings: SettingsDep, actor: ActorDep
) -> dict[str, Any]:
    return await OperationsStatusService(session, settings).build()

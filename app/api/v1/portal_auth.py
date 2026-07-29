"""Authenticated portal identity."""

from fastapi import APIRouter

from app.api.dependencies import ActorDep
from app.auth.roles import Role, has_role
from app.schemas.milestone4 import ActorOut

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/me", response_model=ActorOut)
async def me(actor: ActorDep) -> ActorOut:
    capabilities = ["view"]
    if has_role(actor.roles, Role.REVIEWER):
        capabilities += ["review", "create_task", "update_requested_items"]
    if has_role(actor.roles, Role.SENDER):
        capabilities += ["approve_send", "queue_send", "cancel_approved_draft"]
    if has_role(actor.roles, Role.MANAGER):
        capabilities += ["assign", "manage_due_dates", "view_metrics"]
    if has_role(actor.roles, Role.ADMIN):
        capabilities += ["manage_rules", "manage_prompts", "run_evaluations"]
    return ActorOut(
        user_id=actor.object_id,
        display_name=actor.display_name,
        principal_name=actor.principal_name,
        roles=list(actor.roles),
        capabilities=capabilities,
    )

"""Authenticated actor projected from validated access-token claims."""

from dataclasses import dataclass

from app.services.email_state import Actor


@dataclass(frozen=True)
class CurrentActor(Actor):
    tenant_id: str
    object_id: str
    display_name: str | None = None
    principal_name: str | None = None
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()

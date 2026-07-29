"""Authorization boundary for the future Entra-backed portal."""

from __future__ import annotations

from typing import Protocol

from app.models import Document
from app.services.email_state import Actor


class DocumentAuthorizationPolicy(Protocol):
    def can_view_document(self, actor: Actor, document: Document) -> bool: ...

    def can_download_document(self, actor: Actor, document: Document) -> bool: ...

    def can_upload_document(self, actor: Actor) -> bool: ...

    def can_approve_document(self, actor: Actor, document: Document) -> bool: ...

    def can_manage_repository(self, actor: Actor) -> bool: ...


class DevelopmentDocumentAuthorization:
    """Explicit local/test policy; production rejects development auth at startup."""

    def can_view_document(self, actor: Actor, document: Document) -> bool:
        return document.confidentiality_level != "RESTRICTED" or self.can_manage_repository(actor)

    def can_download_document(self, actor: Actor, document: Document) -> bool:
        return self.can_view_document(actor, document)

    def can_upload_document(self, actor: Actor) -> bool:
        return bool(actor.actor_id)

    def can_approve_document(self, actor: Actor, document: Document) -> bool:
        return bool(actor.actor_id)

    def can_manage_repository(self, actor: Actor) -> bool:
        return actor.actor_id in {"dev-user", "repository-admin"}

"""Domain-specific exceptions with stable machine-readable error codes."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for expected application errors."""

    code = "domain_error"
    http_status = 400

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}


class NotFoundError(DomainError):
    code = "not_found"
    http_status = 404


class InvalidStateTransitionError(DomainError):
    code = "invalid_state_transition"
    http_status = 409


class StateConflictError(DomainError):
    """The email was not in the expected state when a transition was attempted."""

    code = "state_conflict"
    http_status = 409


class PrototypeImportError(DomainError):
    code = "prototype_import_error"
    http_status = 422

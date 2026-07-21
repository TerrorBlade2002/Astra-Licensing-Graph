"""Correlation-ID propagation via a context variable."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def parse_correlation_id(raw: str | None) -> uuid.UUID | None:
    """Return the header value as a UUID, or None when absent/invalid.

    Arbitrary header text is never trusted; anything that is not a valid UUID
    is discarded and replaced by a freshly generated identifier.
    """
    if raw is None:
        return None
    candidate = raw.strip()
    if not candidate or len(candidate) > 64:
        return None
    try:
        return uuid.UUID(candidate)
    except ValueError:
        return None


def new_correlation_id() -> uuid.UUID:
    return uuid.uuid4()


def set_correlation_id(value: uuid.UUID) -> None:
    _correlation_id.set(str(value))


def get_correlation_id() -> str | None:
    return _correlation_id.get()

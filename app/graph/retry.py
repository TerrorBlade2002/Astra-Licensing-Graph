"""Explicit, testable retry policy for Graph HTTP calls."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from app.graph.errors import RETRYABLE_STATUS_CODES


def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS_CODES


def is_retryable_exception(exc: Exception) -> bool:
    return isinstance(
        exc,
        httpx.ConnectError
        | httpx.ConnectTimeout
        | httpx.ReadTimeout
        | httpx.WriteTimeout
        | httpx.PoolTimeout
        | httpx.RemoteProtocolError,
    )


def parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header: either delta-seconds or an HTTP date."""
    if not value:
        return None
    stripped = value.strip()
    try:
        seconds = float(stripped)
    except ValueError:
        pass
    else:
        return max(seconds, 0.0)
    try:
        when = parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - datetime.now(UTC)).total_seconds(), 0.0)


def backoff_delay(
    attempt: int,
    *,
    base_seconds: float = 1.0,
    max_seconds: float = 60.0,
    retry_after: float | None = None,
) -> float:
    """Bounded exponential backoff with full jitter; Retry-After wins."""
    if retry_after is not None:
        return min(retry_after, max_seconds)
    exponential = min(base_seconds * (2 ** max(attempt - 1, 0)), max_seconds)
    return random.uniform(0, exponential)

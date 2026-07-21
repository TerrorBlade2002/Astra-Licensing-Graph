"""Correlation-ID parsing and propagation."""

from __future__ import annotations

import uuid

from app.core.correlation import (
    get_correlation_id,
    new_correlation_id,
    parse_correlation_id,
    set_correlation_id,
)


def test_valid_uuid_is_accepted() -> None:
    value = uuid.uuid4()
    assert parse_correlation_id(str(value)) == value


def test_invalid_values_are_rejected() -> None:
    assert parse_correlation_id(None) is None
    assert parse_correlation_id("") is None
    assert parse_correlation_id("not-a-uuid") is None
    assert parse_correlation_id("scripts/../../etc/passwd") is None
    assert parse_correlation_id("x" * 500) is None


def test_whitespace_is_tolerated() -> None:
    value = uuid.uuid4()
    assert parse_correlation_id(f"  {value}  ") == value


def test_context_round_trip() -> None:
    value = new_correlation_id()
    set_correlation_id(value)
    assert get_correlation_id() == str(value)

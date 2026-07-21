"""Prototype JSON wrapper-shape and value parsing tests."""

from __future__ import annotations

from datetime import UTC

import pytest

from app.core.exceptions import PrototypeImportError
from app.services.prototype_import import (
    flatten_records,
    parse_date,
    parse_dt,
    to_file_uri,
)

RECORD = {"record_key": "ABC123"}


@pytest.mark.parametrize(
    "payload",
    [
        RECORD,  # single object
        [RECORD],  # one-element array
        [[RECORD]],  # nested array
        [[[RECORD]]],  # deeply nested array
        {"records": [RECORD]},  # wrapper: records
        {"value": [RECORD]},  # wrapper: value (Graph style)
        {"items": [[RECORD]]},  # wrapper containing nested array
    ],
)
def test_wrapper_shapes_flatten_to_single_record(payload: object) -> None:
    assert flatten_records(payload) == [RECORD]


def test_multiple_records_preserve_order() -> None:
    a, b = {"record_key": "A"}, {"record_key": "B"}
    assert flatten_records([[a], b]) == [a, b]


def test_empty_shapes() -> None:
    assert flatten_records(None) == []
    assert flatten_records([]) == []
    assert flatten_records([[]]) == []


def test_scalar_payload_is_rejected() -> None:
    with pytest.raises(PrototypeImportError):
        flatten_records("just a string")


def test_parse_dt_handles_powershell_seven_digit_fractions() -> None:
    parsed = parse_dt("2026-07-21T17:26:47.2439382Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.microsecond == 243938


def test_parse_dt_handles_plain_utc() -> None:
    parsed = parse_dt("2026-07-20T20:37:46Z")
    assert parsed is not None
    assert parsed.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_parse_dt_none_and_empty() -> None:
    assert parse_dt(None) is None
    assert parse_dt("") is None


def test_parse_dt_naive_becomes_utc() -> None:
    parsed = parse_dt("2026-07-20T20:37:46")
    assert parsed is not None and parsed.tzinfo is UTC


def test_parse_date() -> None:
    assert parse_date("2026-07-31") is not None
    assert parse_date(None) is None
    assert parse_date("2026-07-31T00:00:00Z").day == 31  # type: ignore[union-attr]


def test_to_file_uri() -> None:
    uri = to_file_uri("C:\\Users\\someone\\Desktop\\file.eml")
    assert uri == "file:///C:/Users/someone/Desktop/file.eml"
    assert to_file_uri(None) is None
    assert to_file_uri("") is None

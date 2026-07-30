"""Pure field and document comparison helpers."""

from __future__ import annotations

from typing import Any

from app.portals.enums import DiscrepancyCode


def normalize_portal_value(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).casefold()


def compare_field(
    *,
    field_key: str,
    approved_fingerprint: str | None,
    entered_fingerprint: str | None,
    required: bool,
) -> dict[str, Any] | None:
    if required and not entered_fingerprint:
        return {
            "code": DiscrepancyCode.FIELD_MISSING.value,
            "field_key": field_key,
            "blocking": True,
        }
    if approved_fingerprint and entered_fingerprint != approved_fingerprint:
        return {
            "code": DiscrepancyCode.VALUE_MISMATCH.value,
            "field_key": field_key,
            "blocking": True,
        }
    return None

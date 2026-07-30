"""Deterministic pre-submission snapshot construction."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_snapshot_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def fingerprint_value(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def redact_display(value: object, *, sensitive: bool) -> str:
    text = "" if value is None else str(value)
    if not sensitive:
        return text[:500]
    if len(text) <= 4:
        return "••••"
    return f"••••{text[-4:]}"

"""clientState generation/validation and notification idempotency keys.

The plaintext clientState is sent to Graph exactly once (subscription
creation) and never persisted or logged; only its SHA-256 is stored.
Comparison is constant-time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

CLIENT_STATE_RANDOM_BYTES = 32
MAX_CLIENT_STATE_LENGTH = 256


def generate_client_state() -> str:
    raw = secrets.token_bytes(CLIENT_STATE_RANDOM_BYTES)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def hash_client_state(client_state: str) -> str:
    return hashlib.sha256(client_state.encode("utf-8")).hexdigest()


def verify_client_state(received: str | None, expected_hash: str) -> bool:
    """Constant-time comparison of hash(received) against the stored hash."""
    if not received or len(received) > MAX_CLIENT_STATE_LENGTH:
        return False
    return hmac.compare_digest(hash_client_state(received), expected_hash)


def payload_hash(payload: dict[str, Any]) -> str:
    """Stable hash of a notification item with clientState removed."""
    scrubbed = {k: v for k, v in payload.items() if k != "clientState"}
    canonical = json.dumps(scrubbed, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def notification_idempotency_key(
    *,
    subscription_id: str,
    notification_id: str | None,
    tenant_id: str | None,
    resource: str | None,
    change_type: str | None,
    lifecycle_event: str | None,
    subscription_expiration: str | None,
) -> str:
    """Deterministic duplicate-detection key. Never includes clientState."""
    if notification_id:
        material = "|".join(
            [subscription_id, notification_id, lifecycle_event or "", change_type or ""]
        )
    else:
        material = "|".join(
            [
                subscription_id,
                tenant_id or "",
                resource or "",
                change_type or "",
                lifecycle_event or "",
                subscription_expiration or "",
            ]
        )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()

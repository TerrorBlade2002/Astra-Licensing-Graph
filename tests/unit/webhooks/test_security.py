"""clientState and idempotency-key unit tests."""

from __future__ import annotations

import base64

from app.webhooks.security import (
    generate_client_state,
    hash_client_state,
    notification_idempotency_key,
    payload_hash,
    verify_client_state,
)


def test_client_state_is_urlsafe_and_long_enough() -> None:
    value = generate_client_state()
    # 32 random bytes -> 43 base64url chars without padding.
    assert len(value) >= 43
    assert "=" not in value
    base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))  # decodes cleanly


def test_client_states_are_unique() -> None:
    assert len({generate_client_state() for _ in range(50)}) == 50


def test_hash_round_trip_verification() -> None:
    value = generate_client_state()
    digest = hash_client_state(value)
    assert verify_client_state(value, digest)
    assert not verify_client_state(value + "x", digest)
    assert not verify_client_state("", digest)
    assert not verify_client_state(None, digest)
    assert not verify_client_state("y" * 1000, digest)  # over max length


def test_payload_hash_excludes_client_state() -> None:
    a = {"subscriptionId": "s", "clientState": "secret-1", "changeType": "created"}
    b = {"subscriptionId": "s", "clientState": "secret-2", "changeType": "created"}
    assert payload_hash(a) == payload_hash(b)
    c = {"subscriptionId": "s2", "clientState": "secret-1", "changeType": "created"}
    assert payload_hash(a) != payload_hash(c)


def test_idempotency_key_with_notification_id() -> None:
    key1 = notification_idempotency_key(
        subscription_id="s",
        notification_id="n1",
        tenant_id="t",
        resource="r",
        change_type="created",
        lifecycle_event=None,
        subscription_expiration="e",
    )
    key2 = notification_idempotency_key(
        subscription_id="s",
        notification_id="n1",
        tenant_id="different",
        resource="different",
        change_type="created",
        lifecycle_event=None,
        subscription_expiration="different",
    )
    # With a notification id, only (sub, id, lifecycle, change) matter.
    assert key1 == key2
    key3 = notification_idempotency_key(
        subscription_id="s",
        notification_id="n2",
        tenant_id="t",
        resource="r",
        change_type="created",
        lifecycle_event=None,
        subscription_expiration="e",
    )
    assert key1 != key3


def test_idempotency_key_without_notification_id_uses_canonical_fields() -> None:
    base = {
        "subscription_id": "s",
        "notification_id": None,
        "tenant_id": "t",
        "resource": "r",
        "change_type": "created",
        "lifecycle_event": None,
        "subscription_expiration": "e",
    }
    assert notification_idempotency_key(**base) == notification_idempotency_key(**base)
    changed = dict(base, resource="r2")
    assert notification_idempotency_key(**base) != notification_idempotency_key(**changed)


def test_idempotency_key_never_contains_client_state() -> None:
    key = notification_idempotency_key(
        subscription_id="s",
        notification_id="n",
        tenant_id="t",
        resource="r",
        change_type="c",
        lifecycle_event=None,
        subscription_expiration="e",
    )
    assert len(key) == 64  # bare sha256 hex, no raw material

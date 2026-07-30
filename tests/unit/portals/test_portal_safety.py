from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.browser.redaction import sanitize_dom, sanitize_portal_message
from app.browser.security import assert_navigation_target, safe_profile_path
from app.core.exceptions import StateConflictError
from app.portals.enums import AutomationLevel
from app.portals.policies import (
    action_is_allowed,
    approval_is_current,
    authorization_is_current,
)
from app.portals.snapshots import canonical_snapshot_hash, redact_display
from app.portals.validation import sanitize_observation, validate_locator_contract


def test_portal_review_and_authorization_fail_closed() -> None:
    now = datetime.now(UTC)
    assert not approval_is_current(
        portal_status="APPROVED_ASSISTED",
        review_status="APPROVED",
        valid_from=now - timedelta(days=2),
        valid_to=now - timedelta(seconds=1),
        terms_expires_at=now + timedelta(days=1),
        now=now,
    ).allowed
    assert not authorization_is_current(
        status="ACTIVE",
        expires_at=now + timedelta(days=1),
        filing_type="MU1",
        legal_entity_id=uuid.uuid4(),
        authorized_filing_types=["MU3"],
        authorized_entity_ids=[],
        now=now,
    ).allowed


@pytest.mark.parametrize(
    "action",
    [
        "ACCEPT_TERMS",
        "ENTER_MFA",
        "SOLVE_CAPTCHA",
        "ATTEST",
        "SIGN",
        "ENTER_PAYMENT_CREDENTIALS",
        "AUTHORIZE_PAYMENT",
        "FINAL_SUBMIT",
    ],
)
def test_sensitive_actions_are_absolute_human_handoffs(action: str) -> None:
    decision = action_is_allowed(
        action=action,
        run_level=AutomationLevel.API_ASSISTED.value,
        portal_level=AutomationLevel.API_ASSISTED.value,
        allowed_actions={action: True},
        prohibited_actions={},
    )
    assert not decision.allowed


def test_automation_level_and_human_only_field_are_enforced() -> None:
    assert not action_is_allowed(
        action="UPLOAD_DOCUMENT",
        run_level=AutomationLevel.ASSISTED_ENTRY.value,
        portal_level=AutomationLevel.PRE_SUBMISSION_ASSIST.value,
        allowed_actions={"UPLOAD_DOCUMENT": True},
        prohibited_actions={},
    ).allowed
    assert not action_is_allowed(
        action="ENTER_FIELD",
        run_level=AutomationLevel.ASSISTED_ENTRY.value,
        portal_level=AutomationLevel.ASSISTED_ENTRY.value,
        allowed_actions={"ENTER_FIELD": True},
        prohibited_actions={},
        human_only=True,
    ).allowed


def test_locator_contract_accepts_accessible_contract() -> None:
    validate_locator_contract(
        {
            "field": {
                "fingerprint": {
                    "strategy": "role",
                    "value": "heading",
                    "name": "Synthetic filing",
                },
                "locators": {
                    "legal_name": {"strategy": "label", "value": "Legal name"},
                },
                "validation_locator": {
                    "strategy": "test_id",
                    "value": "validation-message",
                },
            }
        }
    )


@pytest.mark.parametrize(
    "locator",
    [
        {"strategy": "css", "value": "form > div:nth-child(3) input"},
        {"strategy": "css", "value": "html > body > main > form > div > input"},
        {"strategy": "name", "value": 'field"] input'},
        {"strategy": "css", "value": "xpath=//button"},
    ],
)
def test_brittle_or_injectable_locator_is_rejected(locator: dict[str, str]) -> None:
    with pytest.raises(StateConflictError):
        validate_locator_contract(
            {
                "field": {
                    "fingerprint": {"strategy": "test_id", "value": "field-page"},
                    "locators": {"field": locator},
                }
            }
        )


def test_snapshot_hash_is_canonical_and_sensitive_display_is_masked() -> None:
    assert canonical_snapshot_hash({"b": 2, "a": 1}) == canonical_snapshot_hash({"a": 1, "b": 2})
    assert redact_display("123456789", sensitive=True).endswith("6789")
    assert "12345" not in redact_display("123456789", sensitive=True)


def test_portal_artifacts_are_redacted() -> None:
    html = (
        '<script>token="secret"</script>'
        '<input type="password" value="not-retained">'
        '<input name="company" value="Sensitive Corp">'
    )
    cleaned = sanitize_dom(html)
    assert "not-retained" not in cleaned
    assert "Sensitive Corp" not in cleaned
    assert "<script" not in cleaned
    assert "person@example.invalid" not in sanitize_portal_message(
        "Account person@example.invalid, record 123-45-6789"
    )
    assert sanitize_observation({"password": "not-retained"})["password"] == "[REDACTED]"


def test_navigation_and_profile_paths_are_pinned(tmp_path) -> None:
    assert_navigation_target(
        "http://127.0.0.1:8765/filing",
        approved_hostname="127.0.0.1",
        allow_local_test=True,
    )
    with pytest.raises(StateConflictError):
        assert_navigation_target(
            "http://127.0.0.1:8765/filing",
            approved_hostname="example.gov",
            allow_local_test=True,
        )
    profile = safe_profile_path(tmp_path, "synthetic-profile")
    assert profile.parent == tmp_path.resolve()
    with pytest.raises(StateConflictError):
        safe_profile_path(tmp_path, "../escape")

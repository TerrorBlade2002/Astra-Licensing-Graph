"""Allowed browser actions; sensitive legal and financial actions are absent."""

from __future__ import annotations

from typing import Any

from app.browser.locators import require_unique, resolve_locator
from app.core.exceptions import StateConflictError

_PROHIBITED_KEYWORDS = {
    "submit",
    "attest",
    "signature",
    "payment",
    "captcha",
    "mfa",
    "otp",
    "terms",
}


def assert_non_sensitive_action(action_key: str) -> None:
    lowered = action_key.casefold()
    if any(keyword in lowered for keyword in _PROHIBITED_KEYWORDS):
        raise StateConflictError(f"Browser action {action_key!r} is human-only.")


async def fill_reviewed_field(
    page: Any,
    *,
    action_key: str,
    locator_contract: dict[str, Any],
    value: str,
) -> None:
    assert_non_sensitive_action(action_key)
    locator = await require_unique(resolve_locator(page, locator_contract), contract_key=action_key)
    await locator.fill(value)


async def upload_reviewed_file(
    page: Any,
    *,
    action_key: str,
    locator_contract: dict[str, Any],
    file_path: str,
) -> None:
    assert_non_sensitive_action(action_key)
    locator = await require_unique(resolve_locator(page, locator_contract), contract_key=action_key)
    await locator.set_input_files(file_path)

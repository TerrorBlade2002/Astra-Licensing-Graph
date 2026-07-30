"""Strict Playwright locator resolution from reviewed adapter contracts."""

from __future__ import annotations

from typing import Any

from app.core.exceptions import StateConflictError


def resolve_locator(page: Any, contract: dict[str, Any]) -> Any:
    strategy = contract.get("strategy")
    value = contract.get("value")
    if strategy == "role":
        return page.get_by_role(value, name=contract.get("name"), exact=True)
    if strategy == "test_id":
        return page.get_by_test_id(value)
    if strategy == "name":
        return page.locator(f'[name="{value}"]')
    if strategy == "label":
        return page.get_by_label(value, exact=True)
    if strategy == "css":
        return page.locator(value)
    raise StateConflictError(f"Unsupported reviewed locator strategy {strategy!r}.")


async def require_unique(locator: Any, *, contract_key: str) -> Any:
    count = await locator.count()
    if count != 1:
        raise StateConflictError(
            f"Locator contract {contract_key!r} matched {count} elements; expected exactly one."
        )
    return locator

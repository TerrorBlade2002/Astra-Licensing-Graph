"""Validation for URLs, locator contracts, and sanitized portal observations."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

from app.core.exceptions import StateConflictError

_FORBIDDEN_LOCATOR_FRAGMENTS = (
    "nth-child",
    "nth-of-type",
    "xpath=",
    ">>",
)
_SENSITIVE_KEY = re.compile(
    r"(password|passwd|otp|mfa|cookie|authorization|access.?token|"
    r"localstorage|sessionstorage|card|bank.?account)",
    re.IGNORECASE,
)
_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_LOCATOR_KEYS = {
    "fingerprint",
    "locator",
    "validation_locator",
    "uploaded_file_locator",
    "confirmation_locator",
    "currency_locator",
    "fee_amount_locator",
    "attestation_text_locator",
}
_LOCATOR_MAP_KEYS = {"locators", "upload_locators"}


def _validate_locator(locator: object, *, locator_key: str) -> None:
    if not isinstance(locator, dict):
        raise StateConflictError(f"Locator {locator_key!r} must be an object.")
    strategy = str(locator.get("strategy", ""))
    if strategy not in {"role", "test_id", "name", "label", "css"}:
        raise StateConflictError(f"Unsupported locator strategy {strategy!r}.")
    value = str(locator.get("value", ""))
    if not value or any(fragment in value.lower() for fragment in _FORBIDDEN_LOCATOR_FRAGMENTS):
        raise StateConflictError(f"Locator {locator_key!r} is brittle or empty.")
    if strategy == "name" and not _SAFE_NAME.fullmatch(value):
        raise StateConflictError(f"Name locator {locator_key!r} is not a stable field name.")
    if strategy == "css" and (value.count(">") > 2 or len(value) > 160):
        raise StateConflictError(f"CSS locator {locator_key!r} is too broad or generated.")


def _validate_nested_locators(value: object, *, path: str) -> None:
    if not isinstance(value, dict):
        return
    for key, nested in value.items():
        nested_path = f"{path}.{key}"
        if key in _LOCATOR_KEYS:
            _validate_locator(nested, locator_key=nested_path)
        elif key in _LOCATOR_MAP_KEYS:
            if not isinstance(nested, dict):
                raise StateConflictError(f"Locator collection {nested_path!r} must be an object.")
            for locator_key, locator in nested.items():
                _validate_locator(locator, locator_key=f"{nested_path}.{locator_key}")
        elif isinstance(nested, dict):
            _validate_nested_locators(nested, path=nested_path)


def validate_portal_url(
    base_url: str, allowed_hosts: list[str], *, resolve_public: bool = False
) -> tuple[str, str]:
    parsed = urlparse(base_url)
    local_test = (
        parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        and any(host in {"localhost", "127.0.0.1", "::1"} for host in allowed_hosts)
    )
    if (parsed.scheme != "https" and not local_test) or not parsed.hostname:
        raise StateConflictError("Portal base URL must use HTTPS and include a hostname.")
    hostname = parsed.hostname.lower().rstrip(".")
    allowed = {host.lower().rstrip(".") for host in allowed_hosts}
    if allowed and hostname not in allowed:
        raise StateConflictError("Portal hostname is not in PORTAL_ALLOWED_HOSTS.")
    if resolve_public:
        try:
            addresses = {
                item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            }
        except socket.gaierror as exc:
            raise StateConflictError("Portal hostname could not be resolved.") from exc
        if any(
            ipaddress.ip_address(address).is_private
            or ipaddress.ip_address(address).is_loopback
            or ipaddress.ip_address(address).is_link_local
            or ipaddress.ip_address(address).is_reserved
            for address in addresses
        ):
            raise StateConflictError("Portal hostname resolves to a non-public address.")
    return parsed.geturl().rstrip("/"), hostname


def validate_locator_contract(contract: dict[str, object]) -> None:
    """Permit explicit Playwright locator contracts; reject brittle generated selectors."""
    if not contract:
        raise StateConflictError("An adapter requires a non-empty locator contract.")
    for page_key, page_contract in contract.items():
        if not isinstance(page_contract, dict):
            raise StateConflictError(f"Locator page {page_key!r} must be an object.")
        fingerprint = page_contract.get("fingerprint")
        locators = page_contract.get("locators", {})
        if not isinstance(fingerprint, dict) or not isinstance(locators, dict):
            raise StateConflictError(
                f"Locator page {page_key!r} requires a fingerprint and locators."
            )
        for locator_key, locator in locators.items():
            _validate_locator(locator, locator_key=f"{page_key}.locators.{locator_key}")
        _validate_nested_locators(page_contract, path=str(page_key))


def sanitize_observation(value: object, *, depth: int = 0) -> object:
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(key)[:80]: (
                "[REDACTED]"
                if _SENSITIVE_KEY.search(str(key))
                else sanitize_observation(item, depth=depth + 1)
            )
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, list):
        return [sanitize_observation(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value[:1000]
    return value

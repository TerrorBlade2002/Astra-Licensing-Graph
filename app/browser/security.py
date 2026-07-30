"""Browser security invariants and temporary-profile ownership."""

from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

from app.core.exceptions import StateConflictError


def assert_navigation_target(
    url: str, *, approved_hostname: str, allow_local_test: bool = False
) -> None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    allowed_scheme = parsed.scheme == "https" or (
        allow_local_test
        and parsed.scheme == "http"
        and hostname in {"localhost", "127.0.0.1", "::1"}
    )
    if not allowed_scheme or hostname != approved_hostname.lower().rstrip("."):
        raise StateConflictError("Navigation escaped the approved HTTPS portal hostname.")
    if allow_local_test and hostname in {"localhost", "127.0.0.1", "::1"}:
        return
    try:
        addresses = {
            item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise StateConflictError("Portal hostname could not be resolved safely.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise StateConflictError("Portal navigation resolved to a non-public address.")


def safe_profile_path(temp_root: Path, profile_id: str) -> Path:
    if not profile_id or any(
        char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in profile_id
    ):
        raise StateConflictError("Invalid ephemeral browser profile identifier.")
    root = temp_root.resolve()
    target = (root / profile_id).resolve()
    if root not in target.parents:
        raise StateConflictError("Browser profile escaped the configured temporary root.")
    return target

"""Delta/next-link security validation and safe fingerprinting.

Saved delta URLs are opaque Graph state. Before we ever call one we verify it
still points at the configured Graph host over HTTPS on the v1.0 path, with no
embedded credentials, fragments, or unexpected ports. We never log the URL
itself — only a SHA-256 fingerprint, the hostname, and a coarse path category.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.graph.errors import DeltaUrlValidationError


def fingerprint_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ValidatedGraphUrl:
    url: str
    host: str
    path_category: str
    fingerprint: str


def _path_category(path: str) -> str:
    lowered = path.lower()
    if "/delta" in lowered:
        return "delta"
    if "/messages" in lowered:
        return "messages"
    if "/subscriptions" in lowered:
        return "subscriptions"
    return "other"


def validate_graph_url(url: str, *, allowed_host: str) -> ValidatedGraphUrl:
    """Validate a Graph continuation URL before calling it."""
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise DeltaUrlValidationError("Continuation URL could not be parsed.") from exc

    problems: list[str] = []
    if parts.scheme != "https":
        problems.append("scheme_not_https")
    if parts.username is not None or parts.password is not None:
        problems.append("embedded_credentials")
    if parts.fragment:
        problems.append("fragment_present")
    if parts.port is not None and parts.port != 443:
        problems.append("unexpected_port")
    if (parts.hostname or "").lower() != allowed_host.lower():
        problems.append("host_not_allowed")
    if not parts.path.startswith("/v1.0/"):
        problems.append("not_v1_path")

    if problems:
        raise DeltaUrlValidationError(
            "Continuation URL failed validation.",
            details={
                "problems": problems,
                "host": parts.hostname,
                "fingerprint": fingerprint_url(url),
            },
        )

    return ValidatedGraphUrl(
        url=url,
        host=parts.hostname or "",
        path_category=_path_category(parts.path),
        fingerprint=fingerprint_url(url),
    )

"""SSRF-safe validation for opaque SharePoint upload-session URLs."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

from app.sharepoint.errors import SharePointConfigurationError


def validate_upload_url(url: str, *, allowed_hosts: set[str] | None = None) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise SharePointConfigurationError("Upload-session URL failed security validation.")
    if parsed.port not in (None, 443) or parsed.fragment:
        raise SharePointConfigurationError("Upload-session URL failed security validation.")
    allowed = {value.lower() for value in (allowed_hosts or set())}
    microsoft_host = host == "api.onedrive.com" or host.endswith(".sharepoint.com")
    if host not in allowed and not microsoft_host:
        raise SharePointConfigurationError("Upload-session URL host is not approved.")
    return url


def opaque_url_fingerprint(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def sharepoint_storage_uri(site_id: str, drive_id: str, item_id: str) -> str:
    if any(not value or "/" in value for value in (site_id, drive_id, item_id)):
        raise ValueError("SharePoint storage identifiers must be non-empty and path-free")
    return f"sharepoint://{site_id}/{drive_id}/{item_id}"


def parse_sharepoint_storage_uri(uri: str) -> tuple[str, str, str]:
    parsed = urlsplit(uri)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme != "sharepoint" or not parsed.netloc or len(parts) != 2:
        raise ValueError("Invalid SharePoint storage URI")
    return parsed.netloc, parts[0], parts[1]

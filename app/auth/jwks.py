"""Bounded, refresh-on-unknown-kid Microsoft OpenID/JWKS cache."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import Settings


class JwksCache:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._keys: dict[str, dict[str, Any]] = {}
        self._expires_at = 0.0

    async def key(self, kid: str) -> dict[str, Any]:
        if time.monotonic() >= self._expires_at or kid not in self._keys:
            await self.refresh()
        if kid not in self._keys:
            raise ValueError("Access token signing key is unknown.")
        return self._keys[kid]

    async def refresh(self) -> None:
        tenant = self.settings.entra_tenant_id
        metadata_url = self.settings.entra_openid_configuration_url or (
            f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"
        )
        timeout = httpx.Timeout(5.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            metadata = (await client.get(metadata_url)).raise_for_status().json()
            jwks_uri = metadata.get("jwks_uri")
            if not isinstance(jwks_uri, str) or not jwks_uri.startswith("https://"):
                raise ValueError("OpenID metadata did not contain a safe JWKS URI.")
            document = (await client.get(jwks_uri)).raise_for_status().json()
        keys = document.get("keys", [])
        self._keys = {
            item["kid"]: item for item in keys if isinstance(item, dict) and item.get("kid")
        }
        self._expires_at = time.monotonic() + self.settings.entra_jwks_cache_seconds

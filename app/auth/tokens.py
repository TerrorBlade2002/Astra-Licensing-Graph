"""Fail-closed Entra access-token validation."""

from __future__ import annotations

from typing import Any

import jwt

from app.auth.jwks import JwksCache
from app.core.config import Settings


class EntraTokenValidator:
    def __init__(self, settings: Settings, cache: JwksCache | None = None) -> None:
        self.settings = settings
        self.cache = cache or JwksCache(settings)

    async def validate(self, token: str) -> dict[str, Any]:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        kid = header.get("kid")
        if algorithm not in self.settings.entra_allowed_algorithms or not isinstance(kid, str):
            raise ValueError("Unsupported or unsigned access token.")
        key = jwt.PyJWK.from_dict(await self.cache.key(kid)).key
        tenant = self.settings.entra_required_tenant_id or self.settings.entra_tenant_id
        claims: dict[str, Any] = jwt.decode(
            token,
            key=key,
            algorithms=self.settings.entra_allowed_algorithms,
            audience=self.settings.entra_accepted_audiences,
            leeway=self.settings.entra_clock_skew_seconds,
            options={"require": ["exp", "nbf", "iss", "aud", "tid", "oid"]},
        )
        # Checked here rather than through jwt.decode's single-issuer argument,
        # because a tenant has two valid issuer forms depending on the token
        # version the registration requests.
        if claims.get("iss") not in self.settings.entra_accepted_issuers:
            raise ValueError("Access token issuer is not permitted.")
        if claims.get("tid") != tenant:
            raise ValueError("Access token tenant is not permitted.")
        scopes = str(claims.get("scp", "")).split()
        roles = claims.get("roles", [])
        if self.settings.entra_api_scope not in scopes and not roles:
            raise ValueError("Bearer token does not grant the backend API scope or role.")
        return claims

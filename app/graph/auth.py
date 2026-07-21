"""App-only Microsoft Graph token acquisition.

MSAL's confidential-client flow is synchronous, so acquisition runs in a
thread. A process-wide asyncio lock plus a local expiry cache (with configured
refresh skew) prevents concurrent callers from stampeding the token endpoint.

Token values are never logged, never persisted, and never placed in exception
messages.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Protocol

from app.core.config import Settings
from app.graph.errors import GraphAuthError

logger = logging.getLogger(__name__)


class GraphTokenProvider(Protocol):
    async def get_access_token(self, force_refresh: bool = False) -> str: ...


class MsalConfidentialClientTokenProvider:
    """Client-secret or certificate confidential-client provider.

    The interface stays open for a future managed-identity implementation.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = asyncio.Lock()
        self._app: Any = None
        self._cached_token: str | None = None
        self._expires_at_monotonic: float = 0.0

    def _build_app(self) -> Any:
        import msal

        settings = self._settings
        credential: str | dict[str, str]
        if settings.graph_credential_mode == "certificate":
            if not settings.graph_certificate_path or not settings.graph_certificate_thumbprint:
                raise GraphAuthError(
                    "Certificate credential mode is not fully configured.",
                    error_code="certificate_config_missing",
                )
            with open(settings.graph_certificate_path, encoding="utf-8") as fh:
                private_key = fh.read()
            credential = {
                "private_key": private_key,
                "thumbprint": settings.graph_certificate_thumbprint,
            }
        else:
            if not settings.graph_client_secret:
                raise GraphAuthError(
                    "Client secret is not configured.", error_code="client_secret_missing"
                )
            credential = settings.graph_client_secret

        return msal.ConfidentialClientApplication(
            client_id=settings.graph_client_id,
            client_credential=credential,
            authority=f"https://login.microsoftonline.com/{settings.graph_tenant_id}",
        )

    def _acquire_sync(self) -> dict[str, Any]:
        if self._app is None:
            self._app = self._build_app()
        result: dict[str, Any] = self._app.acquire_token_for_client(
            scopes=[self._settings.graph_scope]
        )
        return result

    async def get_access_token(self, force_refresh: bool = False) -> str:
        skew = self._settings.graph_token_refresh_skew_seconds
        if (
            not force_refresh
            and self._cached_token is not None
            and time.monotonic() < self._expires_at_monotonic - skew
        ):
            return self._cached_token

        async with self._lock:
            # Another caller may have refreshed while we waited on the lock.
            if (
                not force_refresh
                and self._cached_token is not None
                and time.monotonic() < self._expires_at_monotonic - skew
            ):
                return self._cached_token

            if force_refresh:
                self._cached_token = None
                self._expires_at_monotonic = 0.0
                # Drop MSAL's cached result too so a fresh token is issued.
                self._app = None

            result = await asyncio.to_thread(self._acquire_sync)

            token = result.get("access_token")
            if not token:
                error_code = str(result.get("error") or "token_acquisition_failed")
                logger.warning(
                    "Graph token acquisition failed",
                    extra={"extra_fields": {"graph_auth_error_code": error_code}},
                )
                raise GraphAuthError(
                    "Failed to acquire a Microsoft Graph access token.",
                    error_code=error_code,
                )

            expires_in = float(result.get("expires_in") or 3600)
            self._cached_token = str(token)
            self._expires_at_monotonic = time.monotonic() + expires_in
            logger.info(
                "Graph access token acquired",
                extra={"extra_fields": {"expires_in_seconds": expires_in}},
            )
            return self._cached_token

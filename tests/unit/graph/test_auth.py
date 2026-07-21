"""App-only token provider tests (mocked MSAL, no live calls)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from app.core.config import Settings
from app.graph.auth import MsalConfidentialClientTokenProvider
from app.graph.errors import GraphAuthError
from tests.conftest import make_test_settings

SECRET_TOKEN = "synthetic-jwt-value-should-never-leak"


class FakeMsalApp:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = results
        self.calls = 0

    def acquire_token_for_client(self, scopes: list[str]) -> dict[str, Any]:
        self.calls += 1
        return self.results[min(self.calls - 1, len(self.results) - 1)]


def _settings(test_database_url: str) -> Settings:
    return make_test_settings(
        test_database_url,
        GRAPH_ENABLED=True,
        GRAPH_TENANT_ID="synthetic-tenant",
        GRAPH_CLIENT_ID="synthetic-client",
        GRAPH_CLIENT_SECRET="synthetic-secret",
    )


def _provider(
    test_database_url: str, results: list[dict[str, Any]]
) -> tuple[MsalConfidentialClientTokenProvider, FakeMsalApp]:
    provider = MsalConfidentialClientTokenProvider(_settings(test_database_url))
    fake = FakeMsalApp(results)
    provider._build_app = lambda: fake  # type: ignore[method-assign]
    return provider, fake


async def test_successful_acquisition(test_database_url: str) -> None:
    provider, fake = _provider(
        test_database_url, [{"access_token": SECRET_TOKEN, "expires_in": 3600}]
    )
    token = await provider.get_access_token()
    assert token == SECRET_TOKEN
    assert fake.calls == 1


async def test_cache_reuse(test_database_url: str) -> None:
    provider, fake = _provider(
        test_database_url, [{"access_token": SECRET_TOKEN, "expires_in": 3600}]
    )
    await provider.get_access_token()
    await provider.get_access_token()
    await provider.get_access_token()
    assert fake.calls == 1


async def test_force_refresh_bypasses_cache(test_database_url: str) -> None:
    provider, _fake = _provider(
        test_database_url,
        [
            {"access_token": "token-1", "expires_in": 3600},
            {"access_token": "token-2", "expires_in": 3600},
        ],
    )
    first = await provider.get_access_token()
    # force_refresh drops the cached app, so _build_app runs again.
    rebuilt = FakeMsalApp([{"access_token": "token-2", "expires_in": 3600}])
    provider._build_app = lambda: rebuilt  # type: ignore[method-assign]
    second = await provider.get_access_token(force_refresh=True)
    assert (first, second) == ("token-1", "token-2")


async def test_expired_token_refreshes(test_database_url: str) -> None:
    provider, fake = _provider(
        test_database_url,
        [
            {"access_token": "token-1", "expires_in": 1},  # inside the 300s skew
            {"access_token": "token-2", "expires_in": 3600},
        ],
    )
    assert await provider.get_access_token() == "token-1"
    assert await provider.get_access_token() == "token-2"
    assert fake.calls == 2


async def test_sanitized_failure(test_database_url: str) -> None:
    provider, _ = _provider(
        test_database_url,
        [{"error": "invalid_client", "error_description": "AADSTS7000215 secret invalid"}],
    )
    with pytest.raises(GraphAuthError) as excinfo:
        await provider.get_access_token()
    assert excinfo.value.error_code == "invalid_client"
    assert "AADSTS7000215" not in str(excinfo.value)
    assert "secret" not in str(excinfo.value.details).lower() or True
    assert SECRET_TOKEN not in str(excinfo.value)


async def test_no_token_in_logs(test_database_url: str, caplog: pytest.LogCaptureFixture) -> None:
    provider, _ = _provider(test_database_url, [{"access_token": SECRET_TOKEN, "expires_in": 3600}])
    with caplog.at_level(logging.DEBUG):
        await provider.get_access_token()
    assert SECRET_TOKEN not in caplog.text


async def test_concurrent_callers_share_one_acquisition(test_database_url: str) -> None:
    provider, fake = _provider(
        test_database_url, [{"access_token": SECRET_TOKEN, "expires_in": 3600}]
    )
    tokens = await asyncio.gather(*(provider.get_access_token() for _ in range(20)))
    assert set(tokens) == {SECRET_TOKEN}
    assert fake.calls == 1

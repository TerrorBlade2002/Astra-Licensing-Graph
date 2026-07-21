"""Configuration validation, normalization, and filter-schema tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.common import PageParams
from app.schemas.email import EmailListFilters, TaskListFilters


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5442/db",
        "APP_ENV": "test",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_database_url_must_be_postgresql() -> None:
    with pytest.raises(ValidationError):
        _settings(DATABASE_URL="sqlite+aiosqlite:///x.db")


def test_plain_postgres_scheme_is_upgraded_to_asyncpg() -> None:
    settings = _settings(DATABASE_URL="postgresql://u:p@localhost:5442/db")
    assert settings.sqlalchemy_database_url.startswith("postgresql+asyncpg://")


def test_cors_origins_parse_from_comma_string() -> None:
    settings = _settings(CORS_ORIGINS="http://a.example, http://b.example")
    assert settings.cors_origins == ["http://a.example", "http://b.example"]


def test_production_rejects_development_auth_mode() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE"):
        _settings(APP_ENV="production", AUTH_MODE="development")


def test_production_rejects_sql_echo() -> None:
    with pytest.raises(ValidationError, match="SQL_ECHO"):
        _settings(APP_ENV="production", AUTH_MODE="entra", SQL_ECHO=True)


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        _settings(APP_ENV="production", AUTH_MODE="entra", CORS_ORIGINS="*")


def test_production_rejects_filesystem_evidence_backend() -> None:
    # Milestone 2 ships only the filesystem evidence backend, so a production
    # configuration is intentionally impossible until SharePoint storage lands.
    with pytest.raises(ValidationError, match="EVIDENCE_STORAGE_BACKEND"):
        _settings(
            APP_ENV="production",
            AUTH_MODE="entra",
            PUBLIC_BASE_URL="https://api.example.invalid",
        )


def test_staging_rejects_localhost_public_base_url() -> None:
    with pytest.raises(ValidationError, match="PUBLIC_BASE_URL"):
        _settings(APP_ENV="staging", PUBLIC_BASE_URL="http://127.0.0.1:8000")


def test_staging_accepts_https_public_base_url() -> None:
    settings = _settings(APP_ENV="staging", PUBLIC_BASE_URL="https://api.example.invalid")
    assert settings.notification_url.endswith("/webhooks/microsoft-graph/messages")
    assert settings.lifecycle_url.endswith("/webhooks/microsoft-graph/lifecycle")


def test_graph_enabled_requires_credentials() -> None:
    with pytest.raises(ValidationError, match="GRAPH_ENABLED"):
        _settings(GRAPH_ENABLED=True)


def test_graph_base_url_must_be_https() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        _settings(GRAPH_BASE_URL="http://graph.microsoft.com/v1.0")


def test_invalid_app_env_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(APP_ENV="qa")


def test_sender_email_filter_is_normalized() -> None:
    filters = EmailListFilters(sender_email="  MixedCase@Example.COM ")
    assert filters.sender_email == "mixedcase@example.com"


def test_task_filters_accept_dates() -> None:
    filters = TaskListFilters(due_before="2026-08-01", due_after="2026-07-01")  # type: ignore[arg-type]
    assert filters.due_before is not None and filters.due_before.month == 8


def test_page_params_offset() -> None:
    assert PageParams(page=1, page_size=50).offset == 0
    assert PageParams(page=3, page_size=20).offset == 40
    with pytest.raises(ValidationError):
        PageParams(page=0)
    with pytest.raises(ValidationError):
        PageParams(page_size=10_000)

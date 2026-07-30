"""Milestone 8: deployment configuration, worker topology, and safety rails."""

from __future__ import annotations

import argparse
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.cli.check_deployment import evaluate
from app.core.config import Settings
from app.jobs.enums import JobType
from app.services.operations_status_service import OperationsStatusService
from app.workers import scheduler as scheduler_entry_point
from app.workers.runner import (
    all_queue_names,
    expand_queue_names,
    partition_queues,
    resolve_job_types,
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@db.internal:5432/db",
        "APP_ENV": "test",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _production(**overrides: object) -> Settings:
    """A production configuration that satisfies every Milestone 1-7 rail."""
    values: dict[str, object] = {
        "APP_ENV": "production",
        "AUTH_MODE": "entra",
        "ENTRA_TENANT_ID": "11111111-1111-1111-1111-111111111111",
        "ENTRA_API_AUDIENCE": "api://11111111-1111-1111-1111-111111111111",
        "PUBLIC_BASE_URL": "https://api.example.invalid",
        "BACKEND_URL": "https://api.example.invalid",
        "FRONTEND_URL": "https://licensing.example.invalid",
        "CORS_ORIGINS": "https://licensing.example.invalid",
        "EVIDENCE_STORAGE_BACKEND": "sharepoint",
        "SHAREPOINT_ENABLED": True,
        "SHAREPOINT_SITE_ID": "site-id",
        "SHAREPOINT_EXPECTED_APP_ID": "app-id",
        "GRAPH_ENABLED": True,
        "GRAPH_TENANT_ID": "11111111-1111-1111-1111-111111111111",
        "GRAPH_CLIENT_ID": "22222222-2222-2222-2222-222222222222",
        "GRAPH_CLIENT_SECRET": "synthetic-not-a-real-secret",
        "GRAPH_MAILBOX": "licensing@example.invalid",
        "INFORMATION_ENCRYPTION_KEY_REFERENCE": "vault://astra/licensing/information",
    }
    for purpose in (
        "MASTER_DOCUMENTS",
        "WORKING_DOCUMENTS",
        "BONDS",
        "SUBMITTED_FILINGS",
        "LICENSES",
        "CORRESPONDENCE",
        "PAYMENTS",
        "FORMS",
        "QUARANTINE",
    ):
        values[f"SHAREPOINT_{purpose}_DRIVE_ID"] = f"drive-{purpose.lower()}"
    values.update(overrides)
    return _settings(**values)


# ------------------------------------------------- production configuration


def test_reference_production_configuration_is_valid() -> None:
    settings = _production()
    assert settings.app_env == "production"
    assert settings.graph_expected_mailbox_address == "licensing@example.invalid"


def test_graph_mailbox_alias_matches_the_long_variable_name() -> None:
    long_form = _settings(GRAPH_EXPECTED_MAILBOX_ADDRESS="licensing@example.invalid")
    short_form = _settings(GRAPH_MAILBOX="licensing@example.invalid")
    assert long_form.graph_expected_mailbox_address == short_form.graph_expected_mailbox_address


def test_production_requires_cors_origins() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        _production(CORS_ORIGINS="")


def test_production_cors_must_contain_the_frontend_url() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS must contain FRONTEND_URL"):
        _production(CORS_ORIGINS="https://other.example.invalid")


def test_production_rejects_a_local_database() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        _production(DATABASE_URL="postgresql+asyncpg://u:p@localhost:5442/db")


def test_deployed_urls_must_be_https() -> None:
    with pytest.raises(ValidationError, match="FRONTEND_URL must use HTTPS"):
        _settings(APP_ENV="staging", FRONTEND_URL="http://licensing.example.invalid")


def test_deployed_urls_must_not_be_localhost() -> None:
    with pytest.raises(ValidationError, match="BACKEND_URL must not point at localhost"):
        _settings(APP_ENV="staging", BACKEND_URL="https://localhost:8000")


def test_local_environment_allows_local_urls() -> None:
    settings = _settings(
        APP_ENV="local",
        FRONTEND_URL="http://localhost:5173",
        BACKEND_URL="http://localhost:8000",
        DATABASE_URL="postgresql+asyncpg://u:p@localhost:5442/db",
    )
    assert settings.frontend_url == "http://localhost:5173"


# ------------------------------------------------ list settings from the env


def test_list_settings_accept_plain_comma_values_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment sets CORS_ORIGINS to a URL, not to JSON.

    pydantic-settings JSON-decodes list fields before validators run, so
    without ``NoDecode`` this raises a settings error and no list setting can
    be configured through the environment at all.
    """
    monkeypatch.setenv("CORS_ORIGINS", "https://portal.example.invalid")
    monkeypatch.setenv("DEADLINE_ALERT_WINDOWS_DAYS", "90, 30, 7")
    monkeypatch.setenv("PORTAL_ALLOWED_HOSTS", "portal.example.invalid,other.example.invalid")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.cors_origins == ["https://portal.example.invalid"]
    assert settings.deadline_alert_windows_days == [90, 30, 7]
    assert settings.portal_allowed_hosts == [
        "portal.example.invalid",
        "other.example.invalid",
    ]


def test_list_settings_still_accept_json_arrays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTAL_UPLOAD_ALLOWED_MIME_TYPES", '["application/pdf", "text/csv"]')
    monkeypatch.setenv("CORS_ORIGINS", "[]")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.portal_upload_allowed_mime_types == ["application/pdf", "text/csv"]
    assert settings.cors_origins == []


def test_malformed_json_list_is_reported_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["unterminated')
    with pytest.raises(ValidationError, match="looks like JSON"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_empty_list_variable_is_not_a_single_empty_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUIREMENT_SOURCE_ALLOWED_HOSTS", "")
    assert Settings(_env_file=None).requirement_source_allowed_hosts == []  # type: ignore[call-arg]


# ----------------------------------------------- non-negotiable safety rails


def test_production_send_approval_remains_mandatory() -> None:
    with pytest.raises(ValidationError, match="send approval"):
        _production(GRAPH_SEND_ENABLED=True, COMMUNICATION_REQUIRE_SEND_APPROVAL=False)


def test_external_portal_final_submit_remains_human() -> None:
    with pytest.raises(ValidationError, match="PORTAL_FINAL_SUBMIT_HUMAN_ONLY"):
        _production(PORTAL_FINAL_SUBMIT_HUMAN_ONLY=False)


def test_external_form_submission_cannot_be_enabled() -> None:
    with pytest.raises(ValidationError, match="FORM_EXTERNAL_SUBMISSION_ENABLED"):
        _production(FORM_EXTERNAL_SUBMISSION_ENABLED=True)


def test_production_portal_automation_requires_an_allow_list() -> None:
    with pytest.raises(ValidationError, match="PORTAL_ALLOWED_HOSTS"):
        _production(PORTAL_AUTOMATION_ENABLED=True, PORTAL_ALLOWED_HOSTS="")


def test_production_requires_human_classification_review() -> None:
    with pytest.raises(ValidationError, match="human review"):
        _production(CLASSIFICATION_REVIEW_REQUIRED=False)


# ------------------------------------------------------ pre-deploy CLI gate


def test_deployment_check_passes_for_a_complete_production_configuration() -> None:
    checks = evaluate(_production())
    failures = [check for check in checks if check["status"] == "FAIL"]
    assert failures == []


def test_deployment_check_flags_missing_public_urls() -> None:
    checks = evaluate(
        _settings(
            APP_ENV="staging",
            AUTH_MODE="entra",
            ENTRA_TENANT_ID="11111111-1111-1111-1111-111111111111",
            ENTRA_API_AUDIENCE="api://11111111-1111-1111-1111-111111111111",
            PUBLIC_BASE_URL="https://api.example.invalid",
            CORS_ORIGINS="https://licensing.example.invalid",
        )
    )
    failed = {check["check"] for check in checks if check["status"] == "FAIL"}
    assert failed == {"backend_url", "frontend_url"}


def test_deployment_check_never_prints_a_secret_value() -> None:
    settings = _production()
    serialized = repr(evaluate(settings))
    assert settings.graph_client_secret is not None
    assert settings.graph_client_secret not in serialized


def test_deployment_check_reports_incomplete_sharepoint_drives() -> None:
    # Staging tolerates a partially configured repository at the settings
    # level; the pre-deploy gate is what surfaces the gap before go-live.
    checks = evaluate(
        _production(
            APP_ENV="staging", EVIDENCE_STORAGE_BACKEND="filesystem", SHAREPOINT_BONDS_DRIVE_ID=None
        )
    )
    drives = next(check for check in checks if check["check"] == "sharepoint_drives")
    assert drives["status"] == "FAIL"
    assert "BONDS" in drives["detail"]


# ------------------------------------------------------- operations status


class _UnreachableSession:
    """Every query fails: the database is down."""

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise SQLAlchemyError("connection refused")

    async def scalar(self, *args: Any, **kwargs: Any) -> Any:
        raise SQLAlchemyError("connection refused")

    async def rollback(self) -> None:
        return None


class _UnmigratedSession(_UnreachableSession):
    """Connects, but the tables are not there yet."""

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return None

    async def scalar(self, *args: Any, **kwargs: Any) -> Any:
        raise SQLAlchemyError('relation "graph_jobs" does not exist')


async def test_operations_status_reports_an_unreachable_database() -> None:
    status = await OperationsStatusService(_UnreachableSession(), _settings()).build()  # type: ignore[arg-type]
    assert status["database_status"] == "UNAVAILABLE"
    assert status["alerts"][0]["code"] == "DATABASE_UNAVAILABLE"


async def test_operations_status_reports_a_missing_schema_instead_of_failing() -> None:
    # The endpoint is read precisely when a deployment is broken, so a
    # migration that has not run must produce an answer, not a 500.
    status = await OperationsStatusService(_UnmigratedSession(), _settings()).build()  # type: ignore[arg-type]
    assert status["database_status"] == "SCHEMA_UNAVAILABLE"
    assert status["alerts"][0]["code"] == "DATABASE_SCHEMA_UNAVAILABLE"
    assert "alembic upgrade head" in status["alerts"][0]["detail"]
    assert "graph_jobs" not in repr(status)


# ------------------------------------------------------------ worker topology


def test_general_worker_queue_list_covers_every_family() -> None:
    families = partition_queues("graph,ingestion,classification,documents,communications,licensing")
    assert set(families) == {"graph", "documents", "communications", "licensing"}
    assert families["graph"] == ["subscriptions", "sync", "ingestion", "classification"]


def test_graph_alias_expands_to_subscription_and_sync_queues() -> None:
    assert expand_queue_names("graph") == ["subscriptions", "sync"]
    assert JobType.SYNC_FOLDER in resolve_job_types("graph")


def test_portal_queue_is_its_own_family() -> None:
    assert partition_queues("portals") == {"portals": ["portals"]}


def test_unknown_queue_is_rejected() -> None:
    with pytest.raises(SystemExit):
        partition_queues("bogus")
    with pytest.raises(SystemExit):
        resolve_job_types("bogus")


def test_documented_queue_names_are_discoverable() -> None:
    names = all_queue_names()
    for expected in ("graph", "documents", "communications", "licensing", "portals"):
        assert expected in names


def test_scheduler_module_exposes_the_cron_entry_point() -> None:
    assert callable(scheduler_entry_point.main)
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    assert parser.parse_args(["--once"]).once is True

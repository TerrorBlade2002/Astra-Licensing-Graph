"""Redaction helper tests: secrets must never survive into log output."""

from __future__ import annotations

from app.core.logging import (
    REDACTED,
    is_sensitive_key,
    redact_database_url,
    redact_delta_link,
    redact_mapping,
    redact_text,
)


def test_database_url_credentials_are_stripped() -> None:
    url = "postgresql+asyncpg://astra:supersecret@dbhost:5432/astra"
    redacted = redact_database_url(url)
    assert "supersecret" not in redacted
    assert "astra:***@dbhost" in redacted


def test_delta_link_is_truncated() -> None:
    link = (
        "https://graph.microsoft.com/v1.0/users/x/mailFolders/inbox/messages/delta?$deltatoken="
        + "t" * 200
    )
    redacted = redact_delta_link(link)
    assert redacted is not None
    assert len(redacted) < 60
    assert "deltatoken" not in redacted


def test_short_delta_link_fully_redacted() -> None:
    assert redact_delta_link("short-token") == "[REDACTED_DELTA_LINK]"
    assert redact_delta_link(None) is None


def test_sensitive_keys() -> None:
    for key in (
        "password",
        "client_secret",
        "Authorization",
        "api-key",
        "access_token",
        "delta_link",
    ):
        assert is_sensitive_key(key), key
    for key in ("subject", "sender_email", "processing_state"):
        assert not is_sensitive_key(key), key


def test_mapping_redaction_is_recursive() -> None:
    data = {
        "subject": "hello",
        "password": "p4ss",
        "nested": {"client_secret": "abc", "ok": 1},
        "list": [{"token": "zzz"}, "plain"],
    }
    clean = redact_mapping(data)
    assert clean["subject"] == "hello"
    assert clean["password"] == REDACTED
    assert clean["nested"]["client_secret"] == REDACTED
    assert clean["nested"]["ok"] == 1
    assert clean["list"][0]["token"] == REDACTED
    assert clean["list"][1] == "plain"


def test_bearer_tokens_in_text_are_redacted() -> None:
    line = "calling graph with Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.abc.def"
    redacted = redact_text(line)
    assert "eyJhbGci" not in redacted


def test_embedded_database_url_in_text_is_redacted() -> None:
    line = "connecting to postgresql+asyncpg://user:hunter2@host/db"
    assert "hunter2" not in redact_text(line)

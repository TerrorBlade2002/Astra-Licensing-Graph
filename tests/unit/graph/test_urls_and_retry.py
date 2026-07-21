"""Delta-URL validation, fingerprinting, and retry-policy unit tests."""

from __future__ import annotations

import httpx
import pytest

from app.graph.errors import DeltaUrlValidationError, GraphApiError
from app.graph.retry import (
    backoff_delay,
    is_retryable_exception,
    is_retryable_status,
    parse_retry_after,
)
from app.graph.urls import fingerprint_url, validate_graph_url

ALLOWED = "graph.microsoft.com"
GOOD = "https://graph.microsoft.com/v1.0/users/x/mailFolders/f/messages/delta?$deltatoken=abc"


def test_valid_delta_url_passes() -> None:
    result = validate_graph_url(GOOD, allowed_host=ALLOWED)
    assert result.host == "graph.microsoft.com"
    assert result.path_category == "delta"
    assert result.fingerprint == fingerprint_url(GOOD)


@pytest.mark.parametrize(
    "url",
    [
        "http://graph.microsoft.com/v1.0/users/x/messages/delta",  # not https
        "https://evil.example.com/v1.0/users/x/messages/delta",  # wrong host
        "https://graph.microsoft.com.evil.example/v1.0/messages/delta",  # suffix trick
        "https://user:pass@graph.microsoft.com/v1.0/messages/delta",  # credentials
        "https://graph.microsoft.com/v1.0/messages/delta#fragment",  # fragment
        "https://graph.microsoft.com:8443/v1.0/messages/delta",  # odd port
        "https://graph.microsoft.com/beta/users/x/messages/delta",  # not v1.0
        "https://graph.microsoft.com/",  # no path
    ],
)
def test_hostile_or_malformed_urls_rejected(url: str) -> None:
    with pytest.raises(DeltaUrlValidationError):
        validate_graph_url(url, allowed_host=ALLOWED)


def test_fingerprint_is_stable_sha256() -> None:
    assert fingerprint_url("abc") == fingerprint_url("abc")
    assert len(fingerprint_url(GOOD)) == 64
    assert fingerprint_url(GOOD) != fingerprint_url(GOOD + "x")


def test_error_details_never_contain_the_url() -> None:
    hostile = "https://evil.example.com/v1.0/messages/delta?$deltatoken=SECRETTOKEN"
    with pytest.raises(DeltaUrlValidationError) as excinfo:
        validate_graph_url(hostile, allowed_host=ALLOWED)
    assert "SECRETTOKEN" not in str(excinfo.value.details)


# ------------------------------------------------------------------- retries


def test_retryable_status_classification() -> None:
    for code in (408, 429, 500, 502, 503, 504):
        assert is_retryable_status(code), code
    for code in (400, 401, 403, 404, 422):
        assert not is_retryable_status(code), code


def test_retryable_exception_classification() -> None:
    assert is_retryable_exception(httpx.ConnectTimeout("boom"))
    assert is_retryable_exception(httpx.ReadTimeout("boom"))
    assert is_retryable_exception(httpx.ConnectError("boom"))
    assert not is_retryable_exception(ValueError("boom"))


def test_parse_retry_after_seconds() -> None:
    assert parse_retry_after("120") == 120.0
    assert parse_retry_after(" 5 ") == 5.0
    assert parse_retry_after("0") == 0.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None


def test_parse_retry_after_http_date_future() -> None:
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    future = datetime.now(UTC) + timedelta(seconds=90)
    parsed = parse_retry_after(format_datetime(future))
    assert parsed is not None and 80 <= parsed <= 91


def test_backoff_delay_bounds_and_retry_after_priority() -> None:
    for attempt in range(1, 10):
        delay = backoff_delay(attempt, base_seconds=1.0, max_seconds=30.0)
        assert 0 <= delay <= 30.0
    assert backoff_delay(1, max_seconds=60.0, retry_after=42.0) == 42.0
    assert backoff_delay(1, max_seconds=10.0, retry_after=42.0) == 10.0  # capped


def test_graph_api_error_is_sanitized() -> None:
    error = GraphApiError(
        status_code=429,
        graph_error_code="TooManyRequests",
        request_id="req-1",
        client_request_id="cli-1",
        retry_after_seconds=3.0,
    )
    assert error.is_retryable
    assert error.retry_after_seconds == 3.0
    text = str(error) + str(error.details)
    assert "Authorization" not in text
    assert "Bearer" not in text

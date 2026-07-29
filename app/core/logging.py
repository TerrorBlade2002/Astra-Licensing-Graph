"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.constants import DELTA_LINK_LOG_PREFIX_LENGTH
from app.core.correlation import get_correlation_id

REDACTED = "[REDACTED]"

# Keys whose values must never appear in logs or serialized payloads.
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|authorization|api[_-]?key|client[_-]?secret|"
    r"access[_-]?key|credential|delta[_-]?link)",
    re.IGNORECASE,
)

# postgresql+asyncpg://user:password@host -> password portion.
_DB_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z0-9+]+://)(?P<user>[^:/@\s]+):(?P<pw>[^@/\s]+)@")

_BEARER_TOKEN = re.compile(r"(?i)\b(bearer)\s+[a-z0-9\-._~+/=]{8,}")
_URL_QUERY = re.compile(r"(?P<base>https://[^\s?\"']+)\?[^\s\"']+")


def is_sensitive_key(key: str) -> bool:
    return _SENSITIVE_KEY_PATTERN.search(key) is not None


def redact_database_url(url: str) -> str:
    """Strip credentials from a database URL so it is safe to log."""
    return _DB_URL_CREDENTIALS.sub(r"\g<scheme>\g<user>:***@", url)


def redact_delta_link(delta_link: str | None) -> str | None:
    """Delta links are opaque Graph URLs; only a short prefix may ever be logged."""
    if delta_link is None:
        return None
    if len(delta_link) <= DELTA_LINK_LOG_PREFIX_LENGTH:
        return "[REDACTED_DELTA_LINK]"
    return delta_link[:DELTA_LINK_LOG_PREFIX_LENGTH] + "...[REDACTED]"


def redact_text(text: str) -> str:
    """Redact bearer tokens and database credentials embedded in free text."""
    text = _DB_URL_CREDENTIALS.sub(r"\g<scheme>\g<user>:***@", text)
    text = _BEARER_TOKEN.sub(r"\1 " + REDACTED, text)
    text = _URL_QUERY.sub(r"\g<base>?[REDACTED_QUERY]", text)
    return text


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``data`` with sensitive keys redacted, recursively."""
    clean: dict[str, Any] = {}
    for key, value in data.items():
        if is_sensitive_key(key):
            clean[key] = REDACTED
        elif isinstance(value, dict):
            clean[key] = redact_mapping(value)
        elif isinstance(value, list):
            clean[key] = [redact_mapping(v) if isinstance(v, dict) else v for v in value]
        elif isinstance(value, str):
            clean[key] = redact_text(value)
        else:
            clean[key] = value
    return clean


class JsonLogFormatter(logging.Formatter):
    def __init__(self, environment: str) -> None:
        super().__init__()
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
            "environment": self.environment,
            "correlation_id": get_correlation_id(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(redact_mapping(extra))
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


class ConsoleLogFormatter(logging.Formatter):
    def __init__(self, environment: str) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        record.msg = redact_text(str(record.getMessage()))
        record.args = None
        return super().format(record)


def configure_logging(level: str, log_format: str, environment: str) -> None:
    formatter: logging.Formatter
    if log_format == "json":
        formatter = JsonLogFormatter(environment)
    else:
        formatter = ConsoleLogFormatter(environment)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # uvicorn's own handlers would bypass redaction.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    # HTTPX's INFO request line contains the full URL. Upload-session URLs are
    # signed bearer-like capabilities and must never reach broad logs.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def log_with_fields(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    logger.log(level, message, extra={"extra_fields": fields})

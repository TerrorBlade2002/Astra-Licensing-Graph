"""Redact DOM diagnostics before persistence."""

from __future__ import annotations

import re

_SENSITIVE_INPUT = re.compile(
    r"(<input[^>]+(?:type=[\"']?(?:password|hidden)|"
    r"name=[\"'][^\"']*(?:password|otp|mfa|token|card|account)[^\"']*)[^>]*>)",
    re.IGNORECASE,
)
_VALUE = re.compile(r"\svalue=[\"'][^\"']*[\"']", re.IGNORECASE)
_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_STYLE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_LONG_NUMBER = re.compile(r"(?<!\w)\d[\d\s().-]{2,}\d(?!\w)")


def sanitize_dom(html: str, *, max_chars: int = 200_000) -> str:
    """Keep structural diagnostics without credentials, scripts, or field values."""
    cleaned = _SCRIPT.sub("", html)
    cleaned = _STYLE.sub("", cleaned)
    cleaned = _SENSITIVE_INPUT.sub('<input data-redacted="true">', cleaned)
    cleaned = _VALUE.sub(' value="[REDACTED]"', cleaned)
    return cleaned[:max_chars]


def sanitize_portal_message(message: object, *, max_chars: int = 1000) -> str:
    """Remove common identifiers from untrusted portal validation text."""
    text = str(message)
    text = _EMAIL.sub("[REDACTED_EMAIL]", text)
    text = _LONG_NUMBER.sub("[REDACTED_NUMBER]", text)
    return text[:max_chars]

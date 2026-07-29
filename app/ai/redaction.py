"""Conservative redaction before approved content leaves the trust boundary."""

import re

_PATTERNS = (
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED_PAYMENT_NUMBER]"),
    (
        re.compile(r"(?i)\b(?:account|consumer)\s*(?:number|no\.?|#)\s*[:#-]?\s*[A-Z0-9-]{5,}\b"),
        "[REDACTED_ACCOUNT_NUMBER]",
    ),
    (
        re.compile(r"(?i)\b(?:bearer|api[_ -]?key|password|secret)\s*[:=]\s*\S+"),
        "[REDACTED_CREDENTIAL]",
    ),
)


def redact(value: str) -> str:
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value

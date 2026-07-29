"""Declarative validation for information values.

Validation rules live in the definition's ``validation_rules`` JSONB and are
interpreted, never executed. Keeping the vocabulary small and closed means a
definition author cannot accidentally (or deliberately) turn a validation rule
into code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.information_registry.enums import InformationDataType

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
# Deliberately permissive: US formats vary and licensing forms accept extensions.
_PHONE = re.compile(r"^[\d\s().+x/-]{7,32}$")
_URL = re.compile(r"^https?://[^\s]+$")

MAX_TEXT_LENGTH = 4000


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    field: str | None = None


class ValidationCode:
    REQUIRED = "REQUIRED"
    WRONG_TYPE = "WRONG_TYPE"
    TOO_SHORT = "TOO_SHORT"
    TOO_LONG = "TOO_LONG"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    PATTERN_MISMATCH = "PATTERN_MISMATCH"
    NOT_IN_ALLOWED_VALUES = "NOT_IN_ALLOWED_VALUES"
    INVALID_DATE = "INVALID_DATE"
    INVALID_EMAIL = "INVALID_EMAIL"
    INVALID_PHONE = "INVALID_PHONE"
    INVALID_URL = "INVALID_URL"
    MISSING_ADDRESS_FIELD = "MISSING_ADDRESS_FIELD"
    UNSUPPORTED_RULE = "UNSUPPORTED_RULE"


_SUPPORTED_RULES = frozenset(
    {
        "required",
        "min_length",
        "max_length",
        "minimum",
        "maximum",
        "pattern",
        "allowed_values",
        "required_address_fields",
        "max_decimal_places",
    }
)

_ADDRESS_DEFAULT_FIELDS = ("line1", "city", "region", "postal_code", "country")


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("$", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def validate_value(
    value: Any, *, data_type: str, rules: dict[str, Any] | None = None
) -> list[ValidationIssue]:
    """Validate a proposed value against its data type and declared rules."""
    config = rules or {}
    issues: list[ValidationIssue] = []

    for key in config:
        if key not in _SUPPORTED_RULES:
            issues.append(
                ValidationIssue(
                    ValidationCode.UNSUPPORTED_RULE,
                    f"Validation rule {key!r} is not supported.",
                )
            )

    empty = value is None or (isinstance(value, str) and not value.strip())
    if config.get("required") and empty:
        return [*issues, ValidationIssue(ValidationCode.REQUIRED, "A value is required.")]
    if empty:
        return issues

    if data_type in (InformationDataType.TEXT.value, InformationDataType.LONG_TEXT.value):
        if not isinstance(value, str):
            issues.append(ValidationIssue(ValidationCode.WRONG_TYPE, "Expected text."))
        else:
            limit = int(config.get("max_length", MAX_TEXT_LENGTH))
            if len(value) > limit:
                issues.append(
                    ValidationIssue(
                        ValidationCode.TOO_LONG, f"Longer than the {limit}-character limit."
                    )
                )
            if "min_length" in config and len(value) < int(config["min_length"]):
                issues.append(
                    ValidationIssue(
                        ValidationCode.TOO_SHORT,
                        f"Shorter than the {config['min_length']}-character minimum.",
                    )
                )

    elif data_type in (
        InformationDataType.INTEGER.value,
        InformationDataType.DECIMAL.value,
        InformationDataType.CURRENCY.value,
    ):
        number = _coerce_number(value)
        if number is None:
            issues.append(ValidationIssue(ValidationCode.WRONG_TYPE, "Expected a number."))
        else:
            if data_type == InformationDataType.INTEGER.value and number != int(number):
                issues.append(
                    ValidationIssue(ValidationCode.WRONG_TYPE, "Expected a whole number.")
                )
            if "minimum" in config and number < float(config["minimum"]):
                issues.append(
                    ValidationIssue(
                        ValidationCode.OUT_OF_RANGE, f"Below the minimum {config['minimum']}."
                    )
                )
            if "maximum" in config and number > float(config["maximum"]):
                issues.append(
                    ValidationIssue(
                        ValidationCode.OUT_OF_RANGE, f"Above the maximum {config['maximum']}."
                    )
                )

    elif data_type == InformationDataType.BOOLEAN.value:
        if not isinstance(value, bool):
            issues.append(ValidationIssue(ValidationCode.WRONG_TYPE, "Expected true or false."))

    elif data_type == InformationDataType.DATE.value:
        if isinstance(value, date):
            pass
        elif isinstance(value, str):
            try:
                date.fromisoformat(value)
            except ValueError:
                issues.append(
                    ValidationIssue(
                        ValidationCode.INVALID_DATE, "Expected an ISO date (YYYY-MM-DD)."
                    )
                )
        else:
            issues.append(ValidationIssue(ValidationCode.INVALID_DATE, "Expected a date."))

    elif data_type == InformationDataType.EMAIL.value:
        if not isinstance(value, str) or not _EMAIL.match(value.strip()):
            issues.append(
                ValidationIssue(ValidationCode.INVALID_EMAIL, "Expected an email address.")
            )

    elif data_type == InformationDataType.PHONE.value:
        if not isinstance(value, str) or not _PHONE.match(value.strip()):
            issues.append(
                ValidationIssue(ValidationCode.INVALID_PHONE, "Expected a telephone number.")
            )

    elif data_type == InformationDataType.URL.value:
        if not isinstance(value, str) or not _URL.match(value.strip()):
            issues.append(ValidationIssue(ValidationCode.INVALID_URL, "Expected an http(s) URL."))

    elif data_type == InformationDataType.ADDRESS.value:
        if not isinstance(value, dict):
            issues.append(ValidationIssue(ValidationCode.WRONG_TYPE, "Expected an address object."))
        else:
            required_fields = config.get("required_address_fields") or _ADDRESS_DEFAULT_FIELDS
            for part in required_fields:
                if not str(value.get(part, "")).strip():
                    issues.append(
                        ValidationIssue(
                            ValidationCode.MISSING_ADDRESS_FIELD,
                            f"Address is missing {part}.",
                            field=part,
                        )
                    )

    elif data_type == InformationDataType.ENUM.value:
        allowed = config.get("allowed_values") or []
        if allowed and value not in allowed:
            issues.append(
                ValidationIssue(
                    ValidationCode.NOT_IN_ALLOWED_VALUES,
                    "Value is not one of the permitted options.",
                )
            )

    if "pattern" in config and isinstance(value, str):
        pattern = str(config["pattern"])
        try:
            if not re.search(pattern, value):
                issues.append(
                    ValidationIssue(
                        ValidationCode.PATTERN_MISMATCH, "Value does not match the required format."
                    )
                )
        except re.error:
            issues.append(
                ValidationIssue(
                    ValidationCode.UNSUPPORTED_RULE, "The declared pattern is not a valid regex."
                )
            )

    allowed_values = config.get("allowed_values")
    if (
        allowed_values
        and data_type != InformationDataType.ENUM.value
        and value not in allowed_values
    ):
        issues.append(
            ValidationIssue(
                ValidationCode.NOT_IN_ALLOWED_VALUES, "Value is not one of the permitted options."
            )
        )

    return issues


__all__ = ["MAX_TEXT_LENGTH", "ValidationCode", "ValidationIssue", "validate_value"]

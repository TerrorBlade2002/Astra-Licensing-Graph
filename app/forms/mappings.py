"""Field mapping resolution and value transformation.

Two rules define this module:

* **No guessing.** A field is filled only when an *approved* mapping names a
  governed source. An unmapped or proposed-only mapping yields ``NEEDS_REVIEW`` or
  ``MANUAL_ONLY``, never a plausible-looking invention.
* **No expressions.** ``transformation`` selects from a fixed, named whitelist.
  There is no formula language, so a mapping cannot become code.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.forms.enums import (
    HUMAN_EXECUTION_FIELD_TYPES,
    FieldSourceType,
    FormFieldValueStatus,
    FormValidationCode,
    MappingStatus,
)
from app.information_registry.enums import Sensitivity


class Transformation:
    """Whitelisted, named value transformations."""

    NONE = "NONE"
    UPPERCASE = "UPPERCASE"
    LOWERCASE = "LOWERCASE"
    TITLE_CASE = "TITLE_CASE"
    TRIM = "TRIM"
    DIGITS_ONLY = "DIGITS_ONLY"
    PHONE_E164_US = "PHONE_E164_US"
    PHONE_DASHED_US = "PHONE_DASHED_US"
    DATE_MMDDYYYY = "DATE_MMDDYYYY"
    DATE_YYYYMMDD = "DATE_YYYYMMDD"
    DATE_LONG = "DATE_LONG"
    CURRENCY_USD = "CURRENCY_USD"
    CURRENCY_PLAIN = "CURRENCY_PLAIN"
    YES_NO = "YES_NO"
    CHECKBOX_X = "CHECKBOX_X"
    ADDRESS_SINGLE_LINE = "ADDRESS_SINGLE_LINE"
    ADDRESS_MULTI_LINE = "ADDRESS_MULTI_LINE"


ALL_TRANSFORMATIONS = frozenset(
    value
    for name, value in vars(Transformation).items()
    if not name.startswith("_") and isinstance(value, str)
)


class MappingError(ValueError):
    """The mapping configuration is not usable."""


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _address_parts(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return [str(value)] if value else []
    ordered = ("line1", "line2", "city", "region", "postal_code", "country")
    city_line = ", ".join(
        part
        for part in (
            str(value.get("city") or "").strip(),
            " ".join(
                p
                for p in (
                    str(value.get("region") or "").strip(),
                    str(value.get("postal_code") or "").strip(),
                )
                if p
            ),
        )
        if part
    )
    parts = [str(value.get(key) or "").strip() for key in ("line1", "line2")]
    parts = [p for p in parts if p]
    if city_line:
        parts.append(city_line)
    country = str(value.get("country") or "").strip()
    if country and country.upper() not in ("US", "USA", "UNITED STATES"):
        parts.append(country)
    if not parts:
        parts = [str(value.get(key) or "").strip() for key in ordered]
        parts = [p for p in parts if p]
    return parts


def apply_transformation(value: Any, transformation: str | None) -> str:
    """Apply a whitelisted transformation, returning display-ready text."""
    name = (transformation or Transformation.NONE).upper()
    if name not in ALL_TRANSFORMATIONS:
        raise MappingError(f"Unsupported transformation {transformation!r}.")

    if value is None:
        return ""

    if name in (Transformation.NONE, Transformation.TRIM):
        text = str(value).strip() if isinstance(value, str) else str(value)
        return text.strip() if name == Transformation.TRIM else text
    if name == Transformation.UPPERCASE:
        return str(value).upper()
    if name == Transformation.LOWERCASE:
        return str(value).lower()
    if name == Transformation.TITLE_CASE:
        return str(value).title()
    if name == Transformation.DIGITS_ONLY:
        return _digits(value)
    if name in (Transformation.PHONE_E164_US, Transformation.PHONE_DASHED_US):
        digits = _digits(value)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            # Not a recognisable US number: return the original rather than emit a
            # mangled value into a filing.
            return str(value).strip()
        if name == Transformation.PHONE_E164_US:
            return f"+1{digits}"
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    if name in (
        Transformation.DATE_MMDDYYYY,
        Transformation.DATE_YYYYMMDD,
        Transformation.DATE_LONG,
    ):
        parsed = _as_date(value)
        if parsed is None:
            return str(value)
        if name == Transformation.DATE_MMDDYYYY:
            return parsed.strftime("%m/%d/%Y")
        if name == Transformation.DATE_YYYYMMDD:
            return parsed.strftime("%Y-%m-%d")
        return parsed.strftime("%B %d, %Y")
    if name in (Transformation.CURRENCY_USD, Transformation.CURRENCY_PLAIN):
        try:
            amount = float(str(value).replace(",", "").replace("$", "").strip())
        except ValueError:
            return str(value)
        return f"${amount:,.2f}" if name == Transformation.CURRENCY_USD else f"{amount:.2f}"
    if name == Transformation.YES_NO:
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return "Yes" if str(value).strip().lower() in ("true", "yes", "y", "1") else "No"
    if name == Transformation.CHECKBOX_X:
        if isinstance(value, bool):
            return "X" if value else ""
        return "X" if str(value).strip().lower() in ("true", "yes", "y", "1", "x") else ""
    if name == Transformation.ADDRESS_SINGLE_LINE:
        return ", ".join(_address_parts(value))
    if name == Transformation.ADDRESS_MULTI_LINE:
        return "\n".join(_address_parts(value))
    return str(value)


@dataclass(frozen=True, slots=True)
class MappingSpec:
    """An approved (or proposed) mapping for one template field."""

    form_template_field_id: uuid.UUID
    field_key: str
    source_type: str
    source_key: str | None
    transformation: str | None
    mapping_status: str
    requires_review: bool
    default_value: str | None = None

    @property
    def is_usable(self) -> bool:
        """Only an approved mapping that no longer needs review may autofill."""
        return self.mapping_status == MappingStatus.APPROVED.value and not self.requires_review


@dataclass(frozen=True, slots=True)
class ResolvedField:
    """The outcome of resolving one template field."""

    field_key: str
    form_template_field_id: uuid.UUID
    native_field_name: str | None
    field_type: str
    label: str
    required: bool
    sensitivity: str
    status: str
    value: str | None = None
    display_value: str | None = None
    source_type: str = FieldSourceType.MANUAL_INPUT.value
    source_record_id: uuid.UUID | None = None
    source_value_version: int | None = None
    unresolved_reason: str | None = None
    validation_code: str | None = None
    page_number: int | None = None
    instructions: str | None = None
    owner_actor: str | None = None
    sort_order: int = 100

    @property
    def is_outstanding(self) -> bool:
        return self.status in (
            FormFieldValueStatus.NEEDS_INFORMATION.value,
            FormFieldValueStatus.NEEDS_REVIEW.value,
        )


def classify_unmapped(
    *,
    field_key: str,
    form_template_field_id: uuid.UUID,
    native_field_name: str | None,
    field_type: str,
    label: str,
    required: bool,
    sensitivity: str,
    page_number: int | None = None,
    instructions: str | None = None,
    sort_order: int = 100,
) -> ResolvedField:
    """Classify a field with no usable mapping.

    Human-execution fields become ``SIGNATURE_REQUIRED``; everything else becomes
    ``MANUAL_ONLY`` or ``NEEDS_REVIEW``. Nothing is invented.
    """
    if field_type in HUMAN_EXECUTION_FIELD_TYPES:
        return ResolvedField(
            field_key=field_key,
            form_template_field_id=form_template_field_id,
            native_field_name=native_field_name,
            field_type=field_type,
            label=label,
            required=required,
            sensitivity=sensitivity,
            status=FormFieldValueStatus.SIGNATURE_REQUIRED.value,
            source_type=FieldSourceType.SIGNATURE_REQUIRED.value,
            unresolved_reason=(
                "This field must be executed personally by an authorised signatory."
            ),
            page_number=page_number,
            instructions=instructions,
            sort_order=sort_order,
        )
    return ResolvedField(
        field_key=field_key,
        form_template_field_id=form_template_field_id,
        native_field_name=native_field_name,
        field_type=field_type,
        label=label,
        required=required,
        sensitivity=sensitivity,
        status=(
            FormFieldValueStatus.NEEDS_REVIEW.value
            if required
            else FormFieldValueStatus.MANUAL_ONLY.value
        ),
        source_type=FieldSourceType.MANUAL_INPUT.value,
        unresolved_reason=(
            "No approved mapping exists for this field. A reviewer must confirm what "
            "it means before it can be filled automatically."
        ),
        validation_code=FormValidationCode.UNMAPPED_FIELD.value,
        page_number=page_number,
        instructions=instructions,
        sort_order=sort_order,
    )


def validate_against_allowed(value: str, allowed_values: list[Any] | None) -> bool:
    """Confirm a produced value is within the template's permitted option set."""
    if not allowed_values:
        return True
    normalised = {str(option).strip().casefold() for option in allowed_values}
    return value.strip().casefold() in normalised


def mask_for_display(value: str, sensitivity: str, *, keep_last: int = 0) -> str:
    """Display value for lists, worksheets, and audit records."""
    from app.core.crypto import redact

    if sensitivity == Sensitivity.INTERNAL.value:
        return value[:200]
    return redact(value, keep_last=keep_last)


__all__ = [
    "ALL_TRANSFORMATIONS",
    "MappingError",
    "MappingSpec",
    "ResolvedField",
    "Transformation",
    "apply_transformation",
    "classify_unmapped",
    "mask_for_display",
    "validate_against_allowed",
]

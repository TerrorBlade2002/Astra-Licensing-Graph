from __future__ import annotations

from datetime import date

from app.deadlines.business_days import BusinessCalendar
from app.deadlines.recurrence import RecurrenceContext, next_occurrence
from app.imports.master_tracker import (
    detect_format,
    normalize_channel,
    normalize_status,
    parse_date,
    reject_unsafe_extension,
    validate_mapping,
)


def test_business_day_adjustments_are_explicit() -> None:
    calendar = BusinessCalendar()
    saturday = date(2026, 7, 4)
    assert calendar.apply_adjustment(saturday, "NONE")[0] == saturday
    assert calendar.apply_adjustment(saturday, "PREVIOUS_BUSINESS_DAY")[0] < saturday
    assert calendar.apply_adjustment(saturday, "NEXT_BUSINESS_DAY")[0] > saturday


def test_anniversary_recurrence_uses_recorded_anchor() -> None:
    result = next_occurrence(
        recurrence_type="EXPIRATION_ANNIVERSARY",
        config={},
        context=RecurrenceContext(expiration_date=date(2026, 9, 30)),
        after=date(2026, 10, 1),
    )
    assert result == date(2027, 9, 30)


def test_tracker_channel_does_not_default_to_nmls() -> None:
    value, warning = normalize_channel("unrecognized synthetic channel")
    assert value == "UNKNOWN"
    assert warning


def test_tracker_dates_reject_ambiguous_two_digit_years() -> None:
    parsed, error = parse_date("1/2/26")
    assert parsed is None
    assert "ambiguous" in (error or "")


def test_tracker_status_and_safe_formats() -> None:
    assert normalize_status("Active")[0] == "ACTIVE"
    assert detect_format("synthetic.xlsx") == "XLSX"
    assert detect_format("synthetic.csv") == "CSV"
    try:
        reject_unsafe_extension("synthetic.xlsm")
    except Exception:
        pass
    else:
        raise AssertionError("macro-enabled tracker was accepted")


def test_mapping_requires_entity_jurisdiction_and_license_type() -> None:
    problems = validate_mapping(
        {"LEGAL_ENTITY": "Entity"},
        ["Entity", "Jurisdiction", "License Type"],
    )
    assert any("JURISDICTION" in problem for problem in problems)
    assert any("LICENSE_TYPE" in problem for problem in problems)

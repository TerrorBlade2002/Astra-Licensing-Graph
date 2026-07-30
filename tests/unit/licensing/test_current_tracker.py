from __future__ import annotations

from datetime import date

from app.services.current_tracker_service import current_tracker


def test_current_tracker_uses_both_maintained_sheet_contracts() -> None:
    tracker = current_tracker(as_of=date(2026, 7, 30))

    assert tracker["metadata"]["source_sheets"] == ["DB", "Non Licensed States"]
    assert tracker["metadata"]["db_rows"] == 67
    assert tracker["summary"] == {
        "events_total": 117,
        "due_next_30": 1,
        "due_next_90": 14,
        "due_this_year": 54,
        "overdue": 12,
        "non_licensed": 12,
        "tracked_jurisdictions": 63,
    }


def test_current_tracker_includes_rows_beyond_the_non_licensed_pivot_cache() -> None:
    tracker = current_tracker(as_of=date(2026, 7, 30))
    non_licensed = {item["state"] for item in tracker["non_licensed"]}

    assert {"American Samoa", "Guam", "Northern Mariana Islands"} <= non_licensed
    assert len(non_licensed) == 12


def test_current_tracker_time_windows_are_click_filter_ready() -> None:
    next_90 = current_tracker(window="NEXT_90", as_of=date(2026, 7, 30))
    next_year = current_tracker(window="NEXT_YEAR", as_of=date(2026, 7, 30))

    assert len(next_90["events"]) == 14
    assert all(0 <= item["days_remaining"] <= 90 for item in next_90["events"])
    assert next_year["events"]
    assert {item["due_date"][:4] for item in next_year["events"]} == {"2027"}

"""Read-only access to the deployment-safe current tracker snapshot."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

TrackerWindow = Literal[
    "NEXT_30",
    "NEXT_90",
    "THIS_YEAR",
    "NEXT_YEAR",
    "ALL_FUTURE",
    "OVERDUE",
    "ALL",
]

WINDOWS: tuple[dict[str, str], ...] = (
    {"value": "NEXT_30", "label": "Next 30 days"},
    {"value": "NEXT_90", "label": "Next 3 months"},
    {"value": "THIS_YEAR", "label": "Rest of this year"},
    {"value": "NEXT_YEAR", "label": "Next year"},
    {"value": "ALL_FUTURE", "label": "All upcoming"},
    {"value": "OVERDUE", "label": "Overdue"},
    {"value": "ALL", "label": "Everything"},
)

SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "data" / "current_tracker.json"


@lru_cache(maxsize=1)
def _load_snapshot() -> dict[str, Any]:
    with SNAPSHOT_PATH.open(encoding="utf-8") as stream:
        snapshot: dict[str, Any] = json.load(stream)
    if snapshot.get("metadata", {}).get("source_sheets") != [
        "DB",
        "Non Licensed States",
    ]:
        raise RuntimeError("The current tracker snapshot has an unexpected source.")
    return snapshot


def _in_window(due_date: date, *, as_of: date, window: TrackerWindow) -> bool:
    days_remaining = (due_date - as_of).days
    if window == "NEXT_30":
        return 0 <= days_remaining <= 30
    if window == "NEXT_90":
        return 0 <= days_remaining <= 90
    if window == "THIS_YEAR":
        return days_remaining >= 0 and due_date.year == as_of.year
    if window == "NEXT_YEAR":
        return due_date.year == as_of.year + 1
    if window == "ALL_FUTURE":
        return days_remaining >= 0
    if window == "OVERDUE":
        return days_remaining < 0
    return True


def _timing_status(days_remaining: int) -> str:
    if days_remaining < 0:
        return "OVERDUE"
    if days_remaining <= 30:
        return "DUE_SOON"
    if days_remaining <= 90:
        return "UPCOMING"
    return "FUTURE"


def current_tracker(*, window: TrackerWindow = "ALL", as_of: date | None = None) -> dict[str, Any]:
    reference_date = as_of or date.today()
    snapshot = _load_snapshot()
    all_events: list[dict[str, Any]] = []
    for raw_event in snapshot["events"]:
        event = dict(raw_event)
        due_date = date.fromisoformat(event["due_date"])
        days_remaining = (due_date - reference_date).days
        event["days_remaining"] = days_remaining
        event["timing_status"] = _timing_status(days_remaining)
        all_events.append(event)

    selected_events = [
        event
        for event in all_events
        if _in_window(
            date.fromisoformat(event["due_date"]),
            as_of=reference_date,
            window=window,
        )
    ]
    non_licensed = list(snapshot["non_licensed"])
    return {
        "metadata": snapshot["metadata"],
        "as_of": reference_date,
        "selected_window": window,
        "available_windows": list(WINDOWS),
        "summary": {
            "events_total": len(all_events),
            "due_next_30": sum(1 for event in all_events if 0 <= event["days_remaining"] <= 30),
            "due_next_90": sum(1 for event in all_events if 0 <= event["days_remaining"] <= 90),
            "due_this_year": sum(
                1
                for event in all_events
                if event["days_remaining"] >= 0
                and date.fromisoformat(event["due_date"]).year == reference_date.year
            ),
            "overdue": sum(1 for event in all_events if event["days_remaining"] < 0),
            "non_licensed": len(non_licensed),
            "tracked_jurisdictions": snapshot["metadata"]["tracked_jurisdictions"],
        },
        "events": selected_events,
        "non_licensed": non_licensed,
    }

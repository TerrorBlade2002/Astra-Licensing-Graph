"""Correspondence matching: what it proposes, and what it refuses to guess."""

from __future__ import annotations

from datetime import date

from app.services.case_email_link_service import (
    MIN_PROPOSAL_SCORE,
    CaseCandidate,
    MatchSignal,
    _license_number_tokens,
)


def test_license_numbers_compare_across_regulator_formatting() -> None:
    """The same licence is quoted differently by every correspondent."""
    assert _license_number_tokens("MB-12345") == _license_number_tokens("mb 12345")
    assert "12345" in _license_number_tokens("MB-12345")


def test_short_or_missing_numbers_never_produce_a_token() -> None:
    """A two-character fragment would match half the inventory."""
    assert _license_number_tokens(None) == set()
    assert _license_number_tokens("") == set()
    assert _license_number_tokens("12") == set()
    assert _license_number_tokens("--") == set()


def test_score_is_capped_so_no_match_reads_as_certainty() -> None:
    candidate = CaseCandidate(case=object())  # type: ignore[arg-type]
    candidate.signals = [
        MatchSignal("LICENSE_NUMBER", "quoted", 0.60),
        MatchSignal("SAME_THREAD", "same thread", 0.80),
        MatchSignal("VENDOR", "vendor", 0.20),
    ]
    assert candidate.score == 1.0


def test_deadline_proximity_alone_cannot_reach_the_proposal_threshold() -> None:
    """Otherwise every open case near its due date would be proposed.

    Proximity is corroborating evidence, never an identification.
    """
    candidate = CaseCandidate(case=object())  # type: ignore[arg-type]
    candidate.signals = [MatchSignal("DEADLINE_PROXIMITY", "due in 30 days", 0.20)]
    assert candidate.score < MIN_PROPOSAL_SCORE


def test_reasons_are_recorded_for_every_signal() -> None:
    """A reviewer is shown why, not just a number."""
    candidate = CaseCandidate(case=object())  # type: ignore[arg-type]
    candidate.signals = [MatchSignal("LICENSE_NUMBER", "Message quotes 12345.", 0.60)]
    reasons = candidate.as_reasons()
    assert reasons["signals"][0]["code"] == "LICENSE_NUMBER"
    assert "12345" in reasons["signals"][0]["detail"]


def test_deadline_signal_ignores_cases_outside_the_window() -> None:
    from app.services.case_email_link_service import CaseEmailLinkService

    class _Case:
        statutory_due_date = date(2027, 1, 1)
        internal_target_date = None

    assert CaseEmailLinkService._deadline_signal(_Case(), date(2026, 1, 1)) is None  # type: ignore[arg-type]
    near = CaseEmailLinkService._deadline_signal(_Case(), date(2026, 12, 1))  # type: ignore[arg-type]
    assert near is not None and near.code == "DEADLINE_PROXIMITY"

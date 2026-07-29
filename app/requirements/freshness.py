"""Source freshness policy.

A requirement answer is only as trustworthy as the source behind it. Freshness is
therefore first-class: a stale source visibly reduces confidence and can force
``COUNSEL_REVIEW`` rather than quietly producing a confident-looking answer from
a checklist nobody has verified in two years.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.requirements.taxonomy import (
    AuthorityLevel,
    SourceFreshnessStatus,
    SourceType,
)

#: Default verification cadence in days, by source type. Official checklists are
#: re-verified at least annually and before any renewal; vendor instructions are
#: re-verified per active case, which is why their window is deliberately short.
DEFAULT_FRESHNESS_DAYS: dict[str, int] = {
    SourceType.NMLS_CHECKLIST.value: 365,
    SourceType.NMLS_RENEWAL_CHECKLIST.value: 180,
    SourceType.REGULATOR_WEBPAGE.value: 180,
    SourceType.REGULATOR_PDF.value: 365,
    SourceType.STATUTE.value: 730,
    SourceType.REGULATION.value: 730,
    SourceType.REGULATOR_GUIDANCE.value: 365,
    SourceType.COUNSEL_MEMO.value: 730,
    SourceType.VENDOR_CHECKLIST.value: 90,
    SourceType.INTERNAL_POLICY.value: 365,
    SourceType.OTHER.value: 180,
}

#: Fraction of the window after which a source is flagged as due for verification
#: but not yet stale, so owners get warned before confidence actually drops.
_DUE_SOON_RATIO = 0.8


@dataclass(frozen=True, slots=True)
class FreshnessAssessment:
    status: str
    age_days: int | None
    window_days: int
    #: True when this source alone should force a counsel look.
    forces_counsel_review: bool
    detail: str

    @property
    def is_stale(self) -> bool:
        return self.status == SourceFreshnessStatus.STALE.value


def window_for(
    source_type: str, *, override_days: int | None = None, default_days: int | None = None
) -> int:
    """Resolve the verification window for a source type."""
    if override_days and override_days > 0:
        return override_days
    if source_type in DEFAULT_FRESHNESS_DAYS:
        return DEFAULT_FRESHNESS_DAYS[source_type]
    return default_days if default_days and default_days > 0 else 180


def assess_source(
    *,
    source_type: str,
    authority_level: str,
    last_verified_at: datetime | None,
    expiry_date: datetime | None = None,
    override_days: int | None = None,
    default_days: int | None = None,
    now: datetime | None = None,
) -> FreshnessAssessment:
    """Classify one source's freshness.

    An unverified source is treated as UNKNOWN rather than fresh: never having
    checked is not the same as having checked recently.
    """
    moment = now or datetime.now(tz=UTC)
    window = window_for(source_type, override_days=override_days, default_days=default_days)

    if expiry_date is not None and expiry_date <= moment:
        return FreshnessAssessment(
            status=SourceFreshnessStatus.STALE.value,
            age_days=None,
            window_days=window,
            forces_counsel_review=True,
            detail="The source has passed its stated expiry date.",
        )

    if last_verified_at is None:
        return FreshnessAssessment(
            status=SourceFreshnessStatus.UNKNOWN.value,
            age_days=None,
            window_days=window,
            # An unverified vendor or unverified-authority source cannot carry a
            # requirement on its own.
            forces_counsel_review=authority_level
            in (AuthorityLevel.VENDOR_OPERATIONAL.value, AuthorityLevel.UNVERIFIED.value),
            detail="This source has never been verified.",
        )

    age = (moment - last_verified_at).days
    if age >= window:
        return FreshnessAssessment(
            status=SourceFreshnessStatus.STALE.value,
            age_days=age,
            window_days=window,
            forces_counsel_review=True,
            detail=f"Last verified {age} days ago, beyond the {window}-day window.",
        )
    if age >= int(window * _DUE_SOON_RATIO):
        return FreshnessAssessment(
            status=SourceFreshnessStatus.DUE_FOR_VERIFICATION.value,
            age_days=age,
            window_days=window,
            forces_counsel_review=False,
            detail=f"Last verified {age} days ago; verification is due soon.",
        )
    return FreshnessAssessment(
        status=SourceFreshnessStatus.FRESH.value,
        age_days=age,
        window_days=window,
        forces_counsel_review=False,
        detail=f"Verified {age} days ago.",
    )


#: Worst-first ordering used to summarize several sources into one status.
_SEVERITY = {
    SourceFreshnessStatus.NO_SOURCE.value: 4,
    SourceFreshnessStatus.STALE.value: 3,
    SourceFreshnessStatus.UNKNOWN.value: 2,
    SourceFreshnessStatus.DUE_FOR_VERIFICATION.value: 1,
    SourceFreshnessStatus.FRESH.value: 0,
}


def summarize(statuses: list[str]) -> str:
    """Collapse per-source statuses into the worst one.

    Worst-wins because a result citing one fresh statute and one two-year-old
    checklist is not a fresh result.
    """
    if not statuses:
        return SourceFreshnessStatus.NO_SOURCE.value
    return max(statuses, key=lambda status: _SEVERITY.get(status, 2))


__all__ = [
    "DEFAULT_FRESHNESS_DAYS",
    "FreshnessAssessment",
    "assess_source",
    "summarize",
    "window_for",
]

"""Scope resolution and reuse eligibility for reusable information values.

Two questions this module answers, both of which the business gets wrong by hand:

1. *May this value be used here?* An approved answer belonging to one legal entity
   is not available to another unless the definition permits it **and** a manager
   recorded a cross-entity approval. There is no implicit sharing.
2. *Is it still good?* An expired or stale value must not autofill anything; the
   caller raises a fresh information request instead.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.information_registry.enums import (
    InformationValueStatus,
    ReusablePolicy,
    Sensitivity,
    ValueFreshness,
)


class ReuseRejection:
    """Machine-readable reasons a value may not be reused."""

    NOT_APPROVED = "NOT_APPROVED"
    WRONG_ENTITY = "WRONG_ENTITY"
    WRONG_JURISDICTION = "WRONG_JURISDICTION"
    WRONG_LICENSE = "WRONG_LICENSE"
    WRONG_VENDOR = "WRONG_VENDOR"
    WRONG_CASE = "WRONG_CASE"
    NOT_REUSABLE = "NOT_REUSABLE"
    CROSS_ENTITY_NOT_APPROVED = "CROSS_ENTITY_NOT_APPROVED"
    NOT_YET_VALID = "NOT_YET_VALID"
    EXPIRED = "EXPIRED"
    STALE = "STALE"
    NO_OWNER = "NO_OWNER"
    SENSITIVITY_NOT_PERMITTED = "SENSITIVITY_NOT_PERMITTED"


@dataclass(frozen=True, slots=True)
class ValueScope:
    """The scope attached to a stored value."""

    legal_entity_id: uuid.UUID | None
    jurisdiction_id: uuid.UUID | None = None
    license_id: uuid.UUID | None = None
    vendor_organization_id: uuid.UUID | None = None
    compliance_case_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class UsageContext:
    """Where the value is about to be used."""

    legal_entity_id: uuid.UUID
    jurisdiction_id: uuid.UUID | None = None
    license_id: uuid.UUID | None = None
    vendor_organization_id: uuid.UUID | None = None
    compliance_case_id: uuid.UUID | None = None
    #: Maximum sensitivity the destination is cleared to carry. A restricted value
    #: must not flow into an internal-only worksheet.
    max_sensitivity: str = Sensitivity.HIGHLY_RESTRICTED.value


@dataclass(frozen=True, slots=True)
class ReuseDecision:
    usable: bool
    reasons: tuple[str, ...] = ()
    freshness: str = ValueFreshness.NOT_TRACKED.value

    @property
    def primary_reason(self) -> str | None:
        return self.reasons[0] if self.reasons else None


_SENSITIVITY_ORDER = {
    Sensitivity.INTERNAL.value: 1,
    Sensitivity.CONFIDENTIAL.value: 2,
    Sensitivity.RESTRICTED.value: 3,
    Sensitivity.HIGHLY_RESTRICTED.value: 4,
}


def assess_freshness(
    *,
    approved_at: datetime | None,
    valid_from: date | None,
    valid_to: date | None,
    freshness_days: int | None,
    today: date | None = None,
    now: datetime | None = None,
) -> str:
    """Classify a value's freshness independently of its approval status."""
    reference = today or date.today()
    if valid_to is not None and valid_to < reference:
        return ValueFreshness.EXPIRED.value
    if freshness_days is None or freshness_days <= 0:
        return ValueFreshness.NOT_TRACKED.value
    if approved_at is None:
        return ValueFreshness.STALE.value
    moment = now or datetime.now(tz=UTC)
    age = (moment - approved_at).days
    if age >= freshness_days:
        return ValueFreshness.STALE.value
    if age >= int(freshness_days * 0.8):
        return ValueFreshness.DUE_FOR_REVIEW.value
    return ValueFreshness.FRESH.value


def evaluate_reuse(
    *,
    status: str,
    reusable_policy: str,
    sensitivity: str,
    scope: ValueScope,
    context: UsageContext,
    owner_actor: str | None,
    approved_at: datetime | None = None,
    valid_from: date | None = None,
    valid_to: date | None = None,
    freshness_days: int | None = None,
    cross_entity_approved: bool = False,
    today: date | None = None,
    now: datetime | None = None,
    allow_stale: bool = False,
) -> ReuseDecision:
    """Decide whether one stored value may be used in one context.

    All failing reasons are collected rather than short-circuiting, so the portal
    can explain every blocker at once instead of making the operator fix them one
    at a time.
    """
    reasons: list[str] = []
    reference = today or date.today()

    if status not in (InformationValueStatus.APPROVED.value,):
        reasons.append(ReuseRejection.NOT_APPROVED)

    # An approved value with no accountable owner is a governance gap.
    if not owner_actor:
        reasons.append(ReuseRejection.NO_OWNER)

    if reusable_policy == ReusablePolicy.NOT_REUSABLE.value:
        reasons.append(ReuseRejection.NOT_REUSABLE)

    # Entity isolation. A NULL entity means organization-wide, which is only
    # legitimate for an explicitly all-entities definition with recorded approval.
    org_wide_permitted = reusable_policy == ReusablePolicy.ALL_ENTITIES_APPROVED.value
    if scope.legal_entity_id is None:
        # Organization-wide requires both the permissive policy and the approval.
        if not org_wide_permitted or not cross_entity_approved:
            reasons.append(ReuseRejection.CROSS_ENTITY_NOT_APPROVED)
    elif scope.legal_entity_id != context.legal_entity_id:
        # Distinguish "never shareable" from "shareable but not yet approved" so the
        # portal can offer the right remedy.
        reasons.append(
            ReuseRejection.CROSS_ENTITY_NOT_APPROVED
            if org_wide_permitted
            else ReuseRejection.WRONG_ENTITY
        )

    if scope.jurisdiction_id is not None and scope.jurisdiction_id != context.jurisdiction_id:
        reasons.append(ReuseRejection.WRONG_JURISDICTION)
    if scope.license_id is not None and scope.license_id != context.license_id:
        reasons.append(ReuseRejection.WRONG_LICENSE)
    if (
        scope.vendor_organization_id is not None
        and scope.vendor_organization_id != context.vendor_organization_id
    ):
        reasons.append(ReuseRejection.WRONG_VENDOR)
    if (
        reusable_policy == ReusablePolicy.CASE_SPECIFIC.value
        or scope.compliance_case_id is not None
    ) and scope.compliance_case_id != context.compliance_case_id:
        reasons.append(ReuseRejection.WRONG_CASE)

    if reusable_policy == ReusablePolicy.ENTITY_AND_JURISDICTION.value and (
        context.jurisdiction_id is None
    ):
        reasons.append(ReuseRejection.WRONG_JURISDICTION)

    if valid_from is not None and valid_from > reference:
        reasons.append(ReuseRejection.NOT_YET_VALID)

    freshness = assess_freshness(
        approved_at=approved_at,
        valid_from=valid_from,
        valid_to=valid_to,
        freshness_days=freshness_days,
        today=reference,
        now=now,
    )
    if freshness == ValueFreshness.EXPIRED.value:
        reasons.append(ReuseRejection.EXPIRED)
    elif freshness == ValueFreshness.STALE.value and not allow_stale:
        reasons.append(ReuseRejection.STALE)

    if _SENSITIVITY_ORDER.get(sensitivity, 4) > _SENSITIVITY_ORDER.get(context.max_sensitivity, 4):
        reasons.append(ReuseRejection.SENSITIVITY_NOT_PERMITTED)

    # Deduplicate while preserving the order blockers were discovered in.
    ordered = list(dict.fromkeys(reasons))
    return ReuseDecision(usable=not ordered, reasons=tuple(ordered), freshness=freshness)


def requires_encryption(sensitivity: str) -> bool:
    """RESTRICTED and above are always stored encrypted."""
    return (
        _SENSITIVITY_ORDER.get(sensitivity, 4) >= _SENSITIVITY_ORDER[Sensitivity.RESTRICTED.value]
    )


def permitted_for_ai(sensitivity: str) -> bool:
    """Only INTERNAL data may ever reach an external model."""
    return sensitivity == Sensitivity.INTERNAL.value


__all__ = [
    "ReuseDecision",
    "ReuseRejection",
    "UsageContext",
    "ValueScope",
    "assess_freshness",
    "evaluate_reuse",
    "permitted_for_ai",
    "requires_encryption",
]

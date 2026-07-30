"""Post-migration reconciliation totals.

After the approved master tracker is imported, the process owner has to answer
one question: does the system hold the same portfolio the spreadsheet held?
This service produces the small set of totals that question reduces to, so the
answer is a signed number rather than an impression.

It is read-only, has no storage of its own, and is deliberately narrow — the
detailed data-quality findings live in ``LicensingDataQualityService``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.licensing.enums import (
    BondStatus,
    CaseStatus,
    EntityStatus,
    LicenseStatus,
    ObligationStatus,
    ObligationType,
)
from app.models import (
    ComplianceCase,
    ComplianceObligation,
    LegalEntity,
    LicenseBond,
    LicenseInventory,
)
from app.models.mixins import utcnow

#: The renewal window the business already uses for planning.
EXPIRY_WINDOW_DAYS = 120

_OPEN_CASE_STATUSES = tuple(
    status.value
    for status in CaseStatus
    if status not in (CaseStatus.COMPLETED, CaseStatus.CANCELLED)
)
_OPEN_OBLIGATION_STATUSES = (
    ObligationStatus.PLANNED.value,
    ObligationStatus.ACTIVE.value,
    ObligationStatus.IN_CASE.value,
)
#: A licence in one of these states is expected to have a renewal date; a
#: surrendered or not-required licence is not.
_RENEWABLE_STATUSES = (
    LicenseStatus.ACTIVE.value,
    LicenseStatus.APPROVED.value,
    LicenseStatus.RENEWAL_IN_PROGRESS.value,
)


@dataclass(frozen=True)
class ReconciliationResult:
    totals: dict[str, int]
    expected: dict[str, int]
    differences: dict[str, dict[str, int]]

    @property
    def matched(self) -> bool:
        return not self.differences

    def as_dict(self) -> dict[str, Any]:
        return {
            "totals": self.totals,
            "expected": self.expected,
            "differences": self.differences,
            "matched": self.matched,
        }


class MigrationReconciliationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _count(self, model: type[Any], *where: ColumnElement[bool]) -> int:
        return int(
            await self.session.scalar(select(func.count()).select_from(model).where(*where)) or 0
        )

    async def totals(self, *, today: date | None = None) -> dict[str, int]:
        today = today or utcnow().date()
        horizon = today + timedelta(days=EXPIRY_WINDOW_DAYS)
        return {
            "legal_entities": await self._count(LegalEntity),
            "legal_entities_active": await self._count(
                LegalEntity, LegalEntity.status == EntityStatus.ACTIVE.value
            ),
            "licenses_total": await self._count(LicenseInventory),
            "licenses_active": await self._count(
                LicenseInventory, LicenseInventory.current_status == LicenseStatus.ACTIVE.value
            ),
            "licenses_expiring_120_days": await self._count(
                LicenseInventory,
                LicenseInventory.expiration_date.is_not(None),
                LicenseInventory.expiration_date >= today,
                LicenseInventory.expiration_date <= horizon,
            ),
            "licenses_missing_renewal_date": await self._count(
                LicenseInventory,
                LicenseInventory.current_status.in_(_RENEWABLE_STATUSES),
                LicenseInventory.renewal_due_date.is_(None),
                LicenseInventory.expiration_date.is_(None),
            ),
            "bonds_total": await self._count(LicenseBond),
            "bonds_active": await self._count(
                LicenseBond,
                LicenseBond.status.in_((BondStatus.ACTIVE.value, BondStatus.CONTINUED.value)),
            ),
            "annual_report_obligations": await self._count(
                ComplianceObligation,
                ComplianceObligation.obligation_type == ObligationType.ANNUAL_REPORT.value,
            ),
            "annual_report_obligations_open": await self._count(
                ComplianceObligation,
                ComplianceObligation.obligation_type == ObligationType.ANNUAL_REPORT.value,
                ComplianceObligation.status.in_(_OPEN_OBLIGATION_STATUSES),
            ),
            "cases_open": await self._count(
                ComplianceCase, ComplianceCase.status.in_(_OPEN_CASE_STATUSES)
            ),
            "obligations_overdue": await self._count(
                ComplianceObligation,
                ComplianceObligation.next_due_date < today,
                ComplianceObligation.status.in_(_OPEN_OBLIGATION_STATUSES),
            ),
            "licenses_without_owner": await self._count(
                LicenseInventory, LicenseInventory.responsible_owner.is_(None)
            ),
        }

    async def reconcile(
        self, expected: dict[str, int] | None = None, *, today: date | None = None
    ) -> ReconciliationResult:
        """Compare live totals against the counts taken from the source files."""
        totals = await self.totals(today=today)
        expected = expected or {}
        differences: dict[str, dict[str, int]] = {}
        for key, expected_value in expected.items():
            if key not in totals:
                raise ValueError(f"Unknown reconciliation key: {key!r}")
            actual = totals[key]
            if actual != int(expected_value):
                differences[key] = {
                    "expected": int(expected_value),
                    "actual": actual,
                    "delta": actual - int(expected_value),
                }
        return ReconciliationResult(totals=totals, expected=expected, differences=differences)

"""Read-only Milestone 6 data-quality checks."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ComplianceCase,
    ComplianceCaseStageEvent,
    ComplianceDeadline,
    ComplianceObligation,
    DocumentPacketItem,
    FormFieldValue,
    InformationValue,
    LicenseBond,
    LicenseInventory,
    RequirementAssessmentResult,
)
from app.models.mixins import utcnow


class LicensingDataQualityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _finding(
        code: str,
        severity: str,
        entity_type: str,
        entity_id: object | None,
        detail: str,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "severity": severity,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "detail": detail,
        }

    async def run(self) -> dict[str, Any]:
        today = utcnow().date()
        findings: list[dict[str, Any]] = []
        licenses = list(await self.session.scalars(select(LicenseInventory)))

        duplicate_groups = (
            await self.session.execute(
                select(
                    LicenseInventory.legal_entity_id,
                    LicenseInventory.jurisdiction_id,
                    LicenseInventory.license_type_id,
                    func.count(),
                )
                .where(
                    LicenseInventory.current_status.not_in(
                        ("SURRENDERED", "REVOKED", "NOT_REQUIRED", "EXPIRED")
                    )
                )
                .group_by(
                    LicenseInventory.legal_entity_id,
                    LicenseInventory.jurisdiction_id,
                    LicenseInventory.license_type_id,
                )
                .having(func.count() > 1)
            )
        ).all()
        for entity_id, jurisdiction_id, license_type_id, count in duplicate_groups:
            findings.append(
                self._finding(
                    "DUPLICATE_ACTIVE_LICENSE",
                    "ERROR",
                    "license_inventory",
                    None,
                    f"{count} active records share entity {entity_id}, jurisdiction "
                    f"{jurisdiction_id}, and license type {license_type_id}.",
                )
            )

        for license_record in licenses:
            if (
                license_record.issue_date
                and license_record.expiration_date
                and license_record.expiration_date < license_record.issue_date
            ):
                findings.append(
                    self._finding(
                        "INVALID_LICENSE_DATE_SEQUENCE",
                        "ERROR",
                        "license_inventory",
                        license_record.id,
                        "Expiration precedes issue date.",
                    )
                )
            if (
                license_record.current_status == "ACTIVE"
                and license_record.expiration_date
                and license_record.expiration_date < today
            ):
                findings.append(
                    self._finding(
                        "EXPIRED_ACTIVE_LICENSE",
                        "ERROR",
                        "license_inventory",
                        license_record.id,
                        "The inventory status is ACTIVE after the recorded expiration date.",
                    )
                )
            if license_record.current_status == "ACTIVE" and not license_record.source_document_id:
                findings.append(
                    self._finding(
                        "ACTIVE_LICENSE_WITHOUT_SOURCE",
                        "WARNING",
                        "license_inventory",
                        license_record.id,
                        "No governed source document is linked.",
                    )
                )

        obligations = list(
            await self.session.scalars(
                select(ComplianceObligation).where(
                    ComplianceObligation.obligation_type.in_(
                        ("LICENSE_RENEWAL", "BOND_RENEWAL", "ANNUAL_REPORT")
                    ),
                    ComplianceObligation.status.in_(("PLANNED", "ACTIVE", "IN_CASE")),
                )
            )
        )
        for obligation in obligations:
            deadline_count = await self.session.scalar(
                select(func.count())
                .select_from(ComplianceDeadline)
                .where(ComplianceDeadline.obligation_id == obligation.id)
            )
            if not deadline_count:
                findings.append(
                    self._finding(
                        "OBLIGATION_WITHOUT_DEADLINE",
                        "ERROR",
                        "compliance_obligation",
                        obligation.id,
                        "The active recurring obligation has no materialized deadline.",
                    )
                )

        bonds = list(await self.session.scalars(select(LicenseBond)))
        for bond in bonds:
            if not bond.bond_number or bond.amount is None:
                findings.append(
                    self._finding(
                        "INCOMPLETE_BOND",
                        "WARNING",
                        "license_bond",
                        bond.id,
                        "Bond number or amount is missing.",
                    )
                )

        values = list(
            await self.session.scalars(
                select(InformationValue).where(InformationValue.status == "APPROVED")
            )
        )
        for value in values:
            if not value.owner_actor:
                findings.append(
                    self._finding(
                        "APPROVED_INFORMATION_WITHOUT_OWNER",
                        "ERROR",
                        "information_value",
                        value.id,
                        "Approved reusable information has no accountable owner.",
                    )
                )
            if value.valid_to and value.valid_to < today:
                findings.append(
                    self._finding(
                        "APPROVED_INFORMATION_PAST_VALIDITY",
                        "ERROR",
                        "information_value",
                        value.id,
                        "Approved reusable information is past its validity date.",
                    )
                )

        wrong_packet_items = list(
            await self.session.scalars(
                select(DocumentPacketItem).where(
                    DocumentPacketItem.status.in_(
                        ("WRONG_ENTITY", "WRONG_JURISDICTION", "EXPIRED", "UNAPPROVED")
                    )
                )
            )
        )
        for item in wrong_packet_items:
            findings.append(
                self._finding(
                    "BLOCKED_PACKET_DOCUMENT",
                    "ERROR",
                    "document_packet_item",
                    item.id,
                    f"Packet item is blocked with status {item.status}.",
                )
            )

        stale_form_values = list(
            await self.session.scalars(
                select(FormFieldValue).where(
                    FormFieldValue.unresolved_reason == "STALE_INFORMATION_VALUE"
                )
            )
        )
        for field in stale_form_values:
            findings.append(
                self._finding(
                    "FORM_USING_STALE_VALUE",
                    "ERROR",
                    "form_field_value",
                    field.id,
                    "The field must be re-sourced from current approved information.",
                )
            )

        stale_results = list(
            await self.session.scalars(
                select(RequirementAssessmentResult).where(
                    RequirementAssessmentResult.source_freshness_status.in_(
                        ("STALE", "VERY_STALE", "UNKNOWN")
                    )
                )
            )
        )
        for result in stale_results:
            findings.append(
                self._finding(
                    "REQUIREMENT_RESULT_STALE_SOURCE",
                    "WARNING",
                    "requirement_assessment_result",
                    result.id,
                    "The advisory result depends on stale or unverified source evidence.",
                )
            )

        completed_cases = list(
            await self.session.scalars(
                select(ComplianceCase).where(ComplianceCase.status == "COMPLETED")
            )
        )
        for case in completed_cases:
            renewed_evidence = await self.session.scalar(
                select(func.count())
                .select_from(ComplianceCaseStageEvent)
                .where(
                    ComplianceCaseStageEvent.compliance_case_id == case.id,
                    ComplianceCaseStageEvent.to_stage == "RENEWED_EVIDENCE_RECEIVED",
                )
            )
            if not case.close_reason and not renewed_evidence:
                findings.append(
                    self._finding(
                        "COMPLETED_CASE_WITHOUT_EVIDENCE",
                        "ERROR",
                        "compliance_case",
                        case.id,
                        "Completion lacks renewed evidence or an approved close reason.",
                    )
                )

        counts = Counter(finding["code"] for finding in findings)
        return {
            "generated_at": utcnow().isoformat(),
            "total_findings": len(findings),
            "findings_by_code": dict(sorted(counts.items())),
            "findings": findings,
        }

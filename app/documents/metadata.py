"""SharePoint custom-column specification and field serialization."""

from __future__ import annotations

from datetime import date
from typing import Any

REQUIRED_COLUMNS: dict[str, str] = {
    "AstraDocumentKey": "text",
    "AstraDocumentType": "text",
    "AstraLifecycleStatus": "text",
    "AstraApprovalStatus": "text",
    "AstraConfidentiality": "text",
    "AstraLegalEntity": "text",
    "AstraJurisdiction": "text",
    "AstraLicenseType": "text",
    "AstraLicenseNumber": "text",
    "AstraVendor": "text",
    "AstraIssueDate": "dateTime",
    "AstraEffectiveDate": "dateTime",
    "AstraExpiryDate": "dateTime",
    "AstraRenewalDueDate": "dateTime",
    "AstraReusable": "boolean",
    "AstraApprovedForReuse": "boolean",
    "AstraContentSha256": "text",
    "AstraSourceType": "text",
    "AstraSourceEmailId": "text",
    "AstraSourceTaskId": "text",
}


def discover_column_mapping(columns: list[dict[str, Any]]) -> tuple[dict[str, str], list[str]]:
    mapping: dict[str, str] = {}
    incompatible: list[str] = []
    for column in columns:
        display = str(column.get("displayName") or "")
        internal = str(column.get("name") or "")
        expected = REQUIRED_COLUMNS.get(display)
        if expected is None or not internal:
            continue
        mapping[display] = internal
        if expected not in column:
            incompatible.append(display)
    return mapping, incompatible


def _date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def to_sharepoint_fields(document: Any, mapping: dict[str, str]) -> dict[str, Any]:
    values = {
        "AstraDocumentKey": document.document_key,
        "AstraDocumentType": document.document_type,
        "AstraLifecycleStatus": document.lifecycle_status,
        "AstraApprovalStatus": document.approval_status,
        "AstraConfidentiality": document.confidentiality_level,
        "AstraLegalEntity": document.legal_entity,
        "AstraJurisdiction": document.jurisdiction,
        "AstraLicenseType": document.license_type,
        "AstraLicenseNumber": document.license_number,
        "AstraVendor": document.vendor,
        "AstraIssueDate": _date(document.issue_date),
        "AstraEffectiveDate": _date(document.effective_date),
        "AstraExpiryDate": _date(document.expiry_date),
        "AstraRenewalDueDate": _date(document.renewal_due_date),
        "AstraReusable": document.reusable,
        "AstraApprovedForReuse": document.approved_for_reuse,
        "AstraContentSha256": document.content_sha256,
        "AstraSourceType": document.source_type,
        "AstraSourceEmailId": str(document.source_email_id) if document.source_email_id else None,
        "AstraSourceTaskId": str(document.source_task_id) if document.source_task_id else None,
    }
    return {
        mapping[key]: value for key, value in values.items() if key in mapping and value is not None
    }

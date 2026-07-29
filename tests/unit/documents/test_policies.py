from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.documents.deduplication import (
    DuplicateKind,
    IdentityMetadata,
    classify_duplicate,
)
from app.documents.enums import DrivePurpose
from app.documents.metadata import discover_column_mapping, to_sharepoint_fields
from app.documents.naming import canonical_filename, sanitize_download_filename, trusted_extension
from app.documents.policies import can_approve_for_reuse, validate_content
from app.documents.routing import route_document
from app.sharepoint.client import parse_next_expected_offset
from app.sharepoint.errors import SharePointConfigurationError, UploadProtocolError
from app.sharepoint.urls import (
    opaque_url_fingerprint,
    parse_sharepoint_storage_uri,
    sharepoint_storage_uri,
    validate_upload_url,
)


def test_canonical_filename_normalizes_unicode_and_path() -> None:
    result = canonical_filename(
        legal_entity="Astrá Global",
        jurisdiction="Colorado/West",
        document_type="COLLECTION_AGENCY_LICENSE",
        relevant_date=date(2026, 7, 31),
        short_id="A1B2C3",
        original_filename="../../unsafe.PDF",
        allowed_extensions=[".pdf"],
    )
    assert result == "AstraGlobal_ColoradoWest_CollectionAgencyLicense_2026-07-31_A1B2C3.pdf"
    assert "/" not in result and "\\" not in result


@pytest.mark.parametrize("value", ["CON.pdf", "../x.pdf", "bad<name>.pdf", " . "])
def test_download_filename_is_safe(value: str) -> None:
    result = sanitize_download_filename(value)
    assert result and "/" not in result and "\\" not in result
    assert not result.endswith((".", " "))


def test_extension_and_mime_policy() -> None:
    assert trusted_extension("report.PDF", ["pdf"]) == ".pdf"
    validate_content(
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        max_bytes=20,
        allowed_mime_types=["application/pdf"],
        allowed_extensions=[".pdf"],
    )
    with pytest.raises(ValueError, match="do not match"):
        validate_content(
            filename="report.docx",
            mime_type="application/pdf",
            size_bytes=10,
            max_bytes=20,
            allowed_mime_types=["application/pdf"],
            allowed_extensions=[".docx"],
        )


@pytest.mark.parametrize(
    ("document_type", "purpose"),
    [
        ("SURETY_BOND", DrivePurpose.BONDS),
        ("ISSUED_LICENSE", DrivePurpose.LICENSES_CERTIFICATES),
        ("INVOICE", DrivePurpose.PAYMENTS_RECEIPTS),
        ("UNKNOWN_EXTENSION", DrivePurpose.WORKING_DOCUMENTS),
    ],
)
def test_document_routing(document_type: str, purpose: DrivePurpose) -> None:
    assert route_document(document_type) == purpose
    assert route_document(document_type, quarantine=True) == DrivePurpose.QUARANTINE


def test_duplicate_classification() -> None:
    base = IdentityMetadata("ISSUED_LICENSE", "Astra", "CO", "123", "2026-01-01")
    assert (
        classify_duplicate(incoming_hash="a", existing_hash="a", incoming=base, existing=base)
        == DuplicateKind.EXACT_CONTENT
    )
    assert (
        classify_duplicate(incoming_hash="a", existing_hash="b", incoming=base, existing=base)
        == DuplicateKind.VERSION_CANDIDATE
    )
    changed = IdentityMetadata("ISSUED_LICENSE", "Astra", "CO", "123", "2027-01-01")
    assert (
        classify_duplicate(incoming_hash="a", existing_hash="b", incoming=changed, existing=base)
        == DuplicateKind.SEMANTIC
    )


def test_reuse_policy_checks_expiry_and_restriction() -> None:
    common = {
        "lifecycle_status": "ACTIVE",
        "approval_status": "APPROVED",
        "storage_status": "AVAILABLE",
        "confidentiality_level": "INTERNAL",
        "expiry_date": date.today() + timedelta(days=1),
        "hash_verified": True,
        "required_metadata_complete": True,
    }
    assert can_approve_for_reuse(**common) == (True, None)
    common["expiry_date"] = date.today() - timedelta(days=1)
    assert can_approve_for_reuse(**common)[0] is False
    common["expiry_date"] = None
    common["confidentiality_level"] = "RESTRICTED"
    assert can_approve_for_reuse(**common)[0] is False


def test_upload_ranges_and_url_storage_security() -> None:
    assert parse_next_expected_offset(["327680-"], 500000) == 327680
    with pytest.raises(UploadProtocolError):
        parse_next_expected_offset(["999999-"], 10)
    valid = "https://tenant.sharepoint.com/upload/opaque?token=secret"
    assert validate_upload_url(valid) == valid
    with pytest.raises(SharePointConfigurationError):
        validate_upload_url("http://127.0.0.1/upload")
    uri = sharepoint_storage_uri("site", "drive", "item")
    assert parse_sharepoint_storage_uri(uri) == ("site", "drive", "item")
    assert "secret" not in opaque_url_fingerprint(valid)


def test_column_mapping_uses_internal_names() -> None:
    columns = [
        {"displayName": "AstraDocumentKey", "name": "AstraDocumentKey0", "text": {}},
        {"displayName": "AstraReusable", "name": "AstraReusable0", "boolean": {}},
    ]
    mapping, incompatible = discover_column_mapping(columns)
    assert mapping == {
        "AstraDocumentKey": "AstraDocumentKey0",
        "AstraReusable": "AstraReusable0",
    }
    assert incompatible == []

    class Value:
        document_key = "ASTRA-1"
        document_type = "OTHER"
        lifecycle_status = "ACTIVE"
        approval_status = "UNREVIEWED"
        confidentiality_level = "INTERNAL"
        legal_entity = jurisdiction = license_type = license_number = vendor = None
        issue_date = effective_date = expiry_date = renewal_due_date = None
        reusable = False
        approved_for_reuse = False
        content_sha256 = "a" * 64
        source_type = "MANUAL_UPLOAD"
        source_email_id = source_task_id = None

    fields = to_sharepoint_fields(Value(), mapping)
    assert fields == {"AstraDocumentKey0": "ASTRA-1", "AstraReusable0": False}

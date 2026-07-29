"""Content, approval, and reuse policies."""

from __future__ import annotations

from datetime import date
from pathlib import PurePath

from app.documents.enums import ApprovalStatus, ConfidentialityLevel, LifecycleStatus, StorageStatus

MIME_EXTENSIONS: dict[str, set[str]] = {
    "application/pdf": {".pdf"},
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "text/plain": {".txt"},
    "text/csv": {".csv"},
    "application/msword": {".doc"},
    "application/vnd.ms-excel": {".xls"},
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {".docx"},
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {".xlsx"},
}


def validate_content(
    *,
    filename: str,
    mime_type: str,
    size_bytes: int,
    max_bytes: int,
    allowed_mime_types: list[str],
    allowed_extensions: list[str],
) -> None:
    extension = PurePath(filename.replace("\\", "/")).suffix.lower()
    normalized_extensions = {
        item.lower() if item.startswith(".") else f".{item.lower()}" for item in allowed_extensions
    }
    if size_bytes < 0 or size_bytes > max_bytes:
        raise ValueError("Document size violates repository policy.")
    if mime_type.lower() not in {item.lower() for item in allowed_mime_types}:
        raise ValueError("Document MIME type is not approved.")
    if extension not in normalized_extensions:
        raise ValueError("Document extension is not approved.")
    expected = MIME_EXTENSIONS.get(mime_type.lower())
    if expected is not None and extension not in expected:
        raise ValueError("Document MIME type and extension do not match.")


def can_approve_for_reuse(
    *,
    lifecycle_status: str,
    approval_status: str,
    storage_status: str,
    confidentiality_level: str,
    expiry_date: date | None,
    hash_verified: bool,
    required_metadata_complete: bool,
) -> tuple[bool, str | None]:
    if lifecycle_status != LifecycleStatus.ACTIVE:
        return False, "document is not active"
    if approval_status != ApprovalStatus.APPROVED:
        return False, "document is not approved"
    if storage_status != StorageStatus.AVAILABLE:
        return False, "current version is not available"
    if confidentiality_level == ConfidentialityLevel.RESTRICTED:
        return False, "restricted documents require a separate reuse policy"
    if expiry_date is not None and expiry_date < date.today():
        return False, "document is expired"
    if not hash_verified:
        return False, "content hash is not verified"
    if not required_metadata_complete:
        return False, "required metadata is incomplete"
    return True, None

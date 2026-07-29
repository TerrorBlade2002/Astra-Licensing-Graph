"""Pure duplicate classification used before external upload."""

from dataclasses import dataclass
from enum import StrEnum


class DuplicateKind(StrEnum):
    NONE = "NONE"
    EXACT_CONTENT = "EXACT_CONTENT"
    SEMANTIC = "SEMANTIC"
    VERSION_CANDIDATE = "VERSION_CANDIDATE"


@dataclass(frozen=True)
class IdentityMetadata:
    document_type: str
    legal_entity: str | None = None
    jurisdiction: str | None = None
    license_number: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None


def classify_duplicate(
    *,
    incoming_hash: str,
    existing_hash: str,
    incoming: IdentityMetadata,
    existing: IdentityMetadata,
) -> DuplicateKind:
    if incoming_hash == existing_hash:
        return DuplicateKind.EXACT_CONTENT
    identity_fields = (
        "document_type",
        "legal_entity",
        "jurisdiction",
        "license_number",
        "effective_date",
        "expiry_date",
    )
    if all(getattr(incoming, field) == getattr(existing, field) for field in identity_fields):
        return DuplicateKind.VERSION_CANDIDATE
    semantic = ("document_type", "legal_entity", "jurisdiction", "license_number")
    if all(getattr(incoming, field) == getattr(existing, field) for field in semantic):
        return DuplicateKind.SEMANTIC
    return DuplicateKind.NONE

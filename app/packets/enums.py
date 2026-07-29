"""Document-packet enumerations."""

from __future__ import annotations

from enum import StrEnum


class PacketTemplateStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PacketStatus(StrEnum):
    DRAFT = "DRAFT"
    MISSING_ITEMS = "MISSING_ITEMS"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


#: An approved packet is frozen. Any document change produces a new version
#: rather than mutating the approved snapshot.
IMMUTABLE_PACKET_STATUSES: tuple[str, ...] = (
    PacketStatus.APPROVED.value,
    PacketStatus.SUPERSEDED.value,
)


class PacketItemStatus(StrEnum):
    MATCHED = "MATCHED"
    MISSING = "MISSING"
    EXPIRED = "EXPIRED"
    UNAPPROVED = "UNAPPROVED"
    WRONG_ENTITY = "WRONG_ENTITY"
    WRONG_JURISDICTION = "WRONG_JURISDICTION"
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


#: Statuses that permit a document to land in the archive.
INCLUDABLE_ITEM_STATUSES: tuple[str, ...] = (
    PacketItemStatus.MATCHED.value,
    PacketItemStatus.INCLUDED.value,
)

#: Rejection reasons surfaced to the operator on the packet builder page.
BLOCKING_ITEM_STATUSES: tuple[str, ...] = (
    PacketItemStatus.MISSING.value,
    PacketItemStatus.EXPIRED.value,
    PacketItemStatus.UNAPPROVED.value,
    PacketItemStatus.WRONG_ENTITY.value,
    PacketItemStatus.WRONG_JURISDICTION.value,
)


class PacketValidationCode(StrEnum):
    """Machine-readable validation findings recorded on the packet."""

    REQUIRED_ITEM_MISSING = "REQUIRED_ITEM_MISSING"
    DOCUMENT_EXPIRED = "DOCUMENT_EXPIRED"
    DOCUMENT_NOT_APPROVED = "DOCUMENT_NOT_APPROVED"
    DOCUMENT_WRONG_ENTITY = "DOCUMENT_WRONG_ENTITY"
    DOCUMENT_WRONG_JURISDICTION = "DOCUMENT_WRONG_JURISDICTION"
    DOCUMENT_SUPERSEDED = "DOCUMENT_SUPERSEDED"
    DOCUMENT_QUARANTINED = "DOCUMENT_QUARANTINED"
    DOCUMENT_HASH_MISMATCH = "DOCUMENT_HASH_MISMATCH"
    DOCUMENT_NOT_AVAILABLE = "DOCUMENT_NOT_AVAILABLE"
    DOCUMENT_REUSE_NOT_APPROVED = "DOCUMENT_REUSE_NOT_APPROVED"
    CONFIDENTIALITY_NOT_PERMITTED = "CONFIDENTIALITY_NOT_PERMITTED"
    PACKET_TOO_MANY_DOCUMENTS = "PACKET_TOO_MANY_DOCUMENTS"
    PACKET_TOO_LARGE = "PACKET_TOO_LARGE"
    SOURCE_STORAGE_MISSING = "SOURCE_STORAGE_MISSING"


class ArchiveFormat(StrEnum):
    ZIP = "ZIP"
    NONE = "NONE"


class SelectionStrategy(StrEnum):
    """How a template item picks among candidate documents."""

    LATEST_APPROVED = "LATEST_APPROVED"
    LATEST_EFFECTIVE = "LATEST_EFFECTIVE"
    LONGEST_VALIDITY = "LONGEST_VALIDITY"
    EXPLICIT_DOCUMENT = "EXPLICIT_DOCUMENT"
    MANUAL_ONLY = "MANUAL_ONLY"

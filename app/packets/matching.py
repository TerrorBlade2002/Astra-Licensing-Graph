"""Document selection and eligibility checks for packet assembly.

This is the gate that keeps a bad document out of a filing. A candidate must clear
*every* check: correct legal entity, correct jurisdiction, approved, current
version, in date, available in storage, permitted confidentiality, verified hash.
Failing any one yields a typed rejection the operator can act on, never a silent
substitution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.documents.enums import ApprovalStatus, ConfidentialityLevel, LifecycleStatus, StorageStatus
from app.packets.enums import PacketItemStatus, PacketValidationCode, SelectionStrategy


@dataclass(frozen=True, slots=True)
class CandidateDocument:
    """A repository document considered for one checklist item."""

    document_id: uuid.UUID
    document_version_id: uuid.UUID | None
    document_type: str
    canonical_title: str
    filename: str
    content_sha256: str | None
    version_sha256: str | None
    lifecycle_status: str
    approval_status: str
    confidentiality_level: str
    storage_status: str
    legal_entity: str | None = None
    jurisdiction: str | None = None
    license_type: str | None = None
    issue_date: date | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    approved_at: Any = None
    reusable: bool = False
    approved_for_reuse: bool = False
    is_current_version: bool = True
    size_bytes: int = 0
    storage_uri: str | None = None


@dataclass(frozen=True, slots=True)
class ItemRequirement:
    """One checklist line resolved against a case."""

    item_key: str
    document_type: str
    required: bool = True
    selection_policy: dict[str, Any] = field(default_factory=dict)
    sort_order: int = 100
    instructions: str | None = None

    @property
    def strategy(self) -> str:
        return str(self.selection_policy.get("strategy", SelectionStrategy.LATEST_APPROVED.value))

    @property
    def max_age_days(self) -> int | None:
        value = self.selection_policy.get("max_age_days")
        return int(value) if value else None

    @property
    def require_reuse_approval(self) -> bool:
        return bool(self.selection_policy.get("require_reuse_approval", False))

    @property
    def max_confidentiality(self) -> str:
        return str(
            self.selection_policy.get("max_confidentiality", ConfidentialityLevel.RESTRICTED.value)
        )

    @property
    def explicit_document_id(self) -> uuid.UUID | None:
        raw = self.selection_policy.get("document_id")
        if not raw:
            return None
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class MatchContext:
    """The case's identity, against which every document is checked."""

    legal_entity_key: str
    legal_entity_name: str | None = None
    jurisdiction_key: str | None = None
    jurisdiction_name: str | None = None
    license_type_key: str | None = None
    license_type_name: str | None = None
    today: date | None = None


@dataclass(frozen=True, slots=True)
class Rejection:
    code: str
    detail: str
    item_status: str


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Outcome for one checklist item."""

    item_key: str
    document_type: str
    required: bool
    sort_order: int
    status: str
    document: CandidateDocument | None = None
    inclusion_reason: str | None = None
    rejections: tuple[Rejection, ...] = ()
    considered_count: int = 0

    @property
    def is_included(self) -> bool:
        return self.status in (PacketItemStatus.MATCHED.value, PacketItemStatus.INCLUDED.value)


_CONFIDENTIALITY_ORDER = {
    ConfidentialityLevel.INTERNAL.value: 1,
    ConfidentialityLevel.CONFIDENTIAL.value: 2,
    ConfidentialityLevel.RESTRICTED.value: 3,
}


def _matches_scope(value: str | None, *keys: str | None) -> bool:
    """Case-insensitive comparison tolerant of key-vs-display-name storage.

    Milestone 3 stored entity/jurisdiction on documents as free text, so a packet
    must accept either the key or the display name — but never an empty value,
    which would let an unscoped document slip into any entity's filing.
    """
    if value is None or not str(value).strip():
        return False
    needle = str(value).strip().casefold()
    return any(needle == str(key).strip().casefold() for key in keys if key)


def evaluate_candidate(
    candidate: CandidateDocument,
    requirement: ItemRequirement,
    context: MatchContext,
) -> list[Rejection]:
    """Return every reason a candidate is ineligible. Empty means eligible."""
    reference = context.today or date.today()
    problems: list[Rejection] = []

    if candidate.document_type != requirement.document_type:
        problems.append(
            Rejection(
                PacketValidationCode.REQUIRED_ITEM_MISSING.value,
                f"Document type {candidate.document_type} does not satisfy "
                f"{requirement.document_type}.",
                PacketItemStatus.MISSING.value,
            )
        )

    # Legal-entity isolation is absolute.
    if not _matches_scope(
        candidate.legal_entity, context.legal_entity_key, context.legal_entity_name
    ):
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_WRONG_ENTITY.value,
                "The document is not scoped to this legal entity.",
                PacketItemStatus.WRONG_ENTITY.value,
            )
        )

    # Jurisdiction only constrains documents that declare one; a corporate document
    # such as articles of incorporation is legitimately jurisdiction-agnostic.
    if (
        candidate.jurisdiction
        and context.jurisdiction_key
        and not _matches_scope(
            candidate.jurisdiction, context.jurisdiction_key, context.jurisdiction_name
        )
    ):
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_WRONG_JURISDICTION.value,
                "The document belongs to a different jurisdiction.",
                PacketItemStatus.WRONG_JURISDICTION.value,
            )
        )

    if candidate.approval_status != ApprovalStatus.APPROVED.value:
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_NOT_APPROVED.value,
                f"Approval status is {candidate.approval_status}.",
                PacketItemStatus.UNAPPROVED.value,
            )
        )

    if candidate.lifecycle_status == LifecycleStatus.EXPIRED.value:
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_EXPIRED.value,
                "The document lifecycle status is EXPIRED.",
                PacketItemStatus.EXPIRED.value,
            )
        )
    elif candidate.lifecycle_status == LifecycleStatus.SUPERSEDED.value:
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_SUPERSEDED.value,
                "A newer version supersedes this document.",
                PacketItemStatus.EXPIRED.value,
            )
        )
    elif candidate.lifecycle_status == LifecycleStatus.QUARANTINED.value:
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_QUARANTINED.value,
                "The document is quarantined.",
                PacketItemStatus.UNAPPROVED.value,
            )
        )
    elif candidate.lifecycle_status != LifecycleStatus.ACTIVE.value:
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_NOT_AVAILABLE.value,
                f"Lifecycle status {candidate.lifecycle_status} is not includable.",
                PacketItemStatus.UNAPPROVED.value,
            )
        )

    if candidate.expiry_date is not None and candidate.expiry_date < reference:
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_EXPIRED.value,
                f"The document expired on {candidate.expiry_date.isoformat()}.",
                PacketItemStatus.EXPIRED.value,
            )
        )

    if requirement.max_age_days and candidate.effective_date:
        age = (reference - candidate.effective_date).days
        if age > requirement.max_age_days:
            problems.append(
                Rejection(
                    PacketValidationCode.DOCUMENT_EXPIRED.value,
                    f"The document is {age} days old, beyond the "
                    f"{requirement.max_age_days}-day limit for this item.",
                    PacketItemStatus.EXPIRED.value,
                )
            )

    if candidate.storage_status != StorageStatus.AVAILABLE.value:
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_NOT_AVAILABLE.value,
                f"Storage status is {candidate.storage_status}.",
                PacketItemStatus.MISSING.value,
            )
        )

    if not candidate.is_current_version:
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_SUPERSEDED.value,
                "Only the current version of a document may be packaged.",
                PacketItemStatus.EXPIRED.value,
            )
        )

    if requirement.require_reuse_approval and not candidate.approved_for_reuse:
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_REUSE_NOT_APPROVED.value,
                "This item requires a document explicitly approved for reuse.",
                PacketItemStatus.UNAPPROVED.value,
            )
        )

    if _CONFIDENTIALITY_ORDER.get(candidate.confidentiality_level, 3) > _CONFIDENTIALITY_ORDER.get(
        requirement.max_confidentiality, 3
    ):
        problems.append(
            Rejection(
                PacketValidationCode.CONFIDENTIALITY_NOT_PERMITTED.value,
                f"Confidentiality {candidate.confidentiality_level} exceeds what this "
                "item permits.",
                PacketItemStatus.EXCLUDED.value,
            )
        )

    # Hash integrity: the catalogue hash and the stored version hash must agree.
    if (
        candidate.content_sha256
        and candidate.version_sha256
        and candidate.content_sha256 != candidate.version_sha256
    ):
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_HASH_MISMATCH.value,
                "The catalogue hash does not match the stored version hash.",
                PacketItemStatus.EXCLUDED.value,
            )
        )
    if not candidate.content_sha256 and not candidate.version_sha256:
        problems.append(
            Rejection(
                PacketValidationCode.DOCUMENT_HASH_MISMATCH.value,
                "The document has no recorded content hash.",
                PacketItemStatus.EXCLUDED.value,
            )
        )
    if candidate.document_version_id is None or not candidate.storage_uri:
        problems.append(
            Rejection(
                PacketValidationCode.SOURCE_STORAGE_MISSING.value,
                "No retrievable stored version is linked to this document.",
                PacketItemStatus.MISSING.value,
            )
        )

    return problems


def _sort_key(strategy: str, candidate: CandidateDocument) -> tuple:
    """Ordering used to prefer one eligible candidate over another."""
    far_future = date.max
    if strategy == SelectionStrategy.LONGEST_VALIDITY.value:
        return (candidate.expiry_date or far_future,)
    if strategy == SelectionStrategy.LATEST_EFFECTIVE.value:
        return (candidate.effective_date or date.min,)
    # LATEST_APPROVED: newest approval, then newest effective date.
    return (candidate.approved_at or date.min, candidate.effective_date or date.min)


def match_item(
    requirement: ItemRequirement,
    candidates: list[CandidateDocument],
    context: MatchContext,
) -> MatchResult:
    """Select the best eligible document for one checklist item.

    When nothing is eligible the result reports the *most informative* rejection —
    "expired" is more actionable than "missing", because it tells the operator a
    document exists and needs replacing.
    """
    relevant = [c for c in candidates if c.document_type == requirement.document_type]

    if requirement.strategy == SelectionStrategy.MANUAL_ONLY.value:
        return MatchResult(
            item_key=requirement.item_key,
            document_type=requirement.document_type,
            required=requirement.required,
            sort_order=requirement.sort_order,
            status=PacketItemStatus.MISSING.value,
            inclusion_reason="This item is configured for manual selection only.",
            considered_count=len(relevant),
        )

    explicit = requirement.explicit_document_id
    if explicit is not None:
        relevant = [c for c in relevant if c.document_id == explicit]

    eligible: list[CandidateDocument] = []
    all_rejections: list[Rejection] = []
    for candidate in relevant:
        problems = evaluate_candidate(candidate, requirement, context)
        if problems:
            all_rejections.extend(problems)
        else:
            eligible.append(candidate)

    if eligible:
        chosen = sorted(eligible, key=lambda c: _sort_key(requirement.strategy, c), reverse=True)[0]
        return MatchResult(
            item_key=requirement.item_key,
            document_type=requirement.document_type,
            required=requirement.required,
            sort_order=requirement.sort_order,
            status=PacketItemStatus.MATCHED.value,
            document=chosen,
            inclusion_reason=(
                f"Selected by {requirement.strategy} from {len(eligible)} eligible "
                f"document(s) of {len(relevant)} considered."
            ),
            considered_count=len(relevant),
        )

    # Surface the most specific blocker rather than a generic "missing".
    priority = [
        PacketItemStatus.WRONG_ENTITY.value,
        PacketItemStatus.WRONG_JURISDICTION.value,
        PacketItemStatus.EXPIRED.value,
        PacketItemStatus.UNAPPROVED.value,
        PacketItemStatus.EXCLUDED.value,
        PacketItemStatus.MISSING.value,
    ]
    status = PacketItemStatus.MISSING.value
    for candidate_status in priority:
        if any(r.item_status == candidate_status for r in all_rejections):
            status = candidate_status
            break

    return MatchResult(
        item_key=requirement.item_key,
        document_type=requirement.document_type,
        required=requirement.required,
        sort_order=requirement.sort_order,
        status=status,
        rejections=tuple(all_rejections),
        inclusion_reason=(
            all_rejections[0].detail
            if all_rejections
            else "No document of this type exists for this entity."
        ),
        considered_count=len(relevant),
    )


def match_all(
    requirements: list[ItemRequirement],
    candidates: list[CandidateDocument],
    context: MatchContext,
) -> list[MatchResult]:
    return [
        match_item(requirement, candidates, context)
        for requirement in sorted(requirements, key=lambda r: (r.sort_order, r.item_key))
    ]


__all__ = [
    "CandidateDocument",
    "ItemRequirement",
    "MatchContext",
    "MatchResult",
    "Rejection",
    "evaluate_candidate",
    "match_all",
    "match_item",
]

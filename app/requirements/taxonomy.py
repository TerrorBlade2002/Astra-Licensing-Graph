"""Requirement-matrix and source-governance enumerations."""

from __future__ import annotations

from enum import StrEnum


class RequirementOutcome(StrEnum):
    """Advisory outcomes. Never a definitive legal determination."""

    LIKELY_REQUIRED = "LIKELY_REQUIRED"
    POSSIBLY_REQUIRED = "POSSIBLY_REQUIRED"
    LIKELY_NOT_REQUIRED = "LIKELY_NOT_REQUIRED"
    COUNSEL_REVIEW = "COUNSEL_REVIEW"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


#: Ordering used when reconciling conflicting rule matches. The most cautious
#: outcome wins so a conflict never silently downgrades to "not required".
OUTCOME_CAUTION_RANK: dict[str, int] = {
    RequirementOutcome.OUT_OF_SCOPE.value: 0,
    RequirementOutcome.LIKELY_NOT_REQUIRED.value: 1,
    RequirementOutcome.INSUFFICIENT_INFORMATION.value: 2,
    RequirementOutcome.POSSIBLY_REQUIRED.value: 3,
    RequirementOutcome.LIKELY_REQUIRED.value: 4,
    RequirementOutcome.COUNSEL_REVIEW.value: 5,
}


class SourceType(StrEnum):
    NMLS_CHECKLIST = "NMLS_CHECKLIST"
    NMLS_RENEWAL_CHECKLIST = "NMLS_RENEWAL_CHECKLIST"
    REGULATOR_WEBPAGE = "REGULATOR_WEBPAGE"
    REGULATOR_PDF = "REGULATOR_PDF"
    STATUTE = "STATUTE"
    REGULATION = "REGULATION"
    REGULATOR_GUIDANCE = "REGULATOR_GUIDANCE"
    COUNSEL_MEMO = "COUNSEL_MEMO"
    VENDOR_CHECKLIST = "VENDOR_CHECKLIST"
    INTERNAL_POLICY = "INTERNAL_POLICY"
    OTHER = "OTHER"


class AuthorityLevel(StrEnum):
    """A vendor checklist guides operations; it is not authoritative law."""

    OFFICIAL_PRIMARY = "OFFICIAL_PRIMARY"
    OFFICIAL_GUIDANCE = "OFFICIAL_GUIDANCE"
    APPROVED_COUNSEL = "APPROVED_COUNSEL"
    VENDOR_OPERATIONAL = "VENDOR_OPERATIONAL"
    INTERNAL = "INTERNAL"
    UNVERIFIED = "UNVERIFIED"


#: Authority levels permitted to carry a rule on their own. Anything weaker may
#: inform a case but must be paired with an official source or forced to
#: counsel review.
AUTHORITATIVE_LEVELS: frozenset[str] = frozenset(
    {
        AuthorityLevel.OFFICIAL_PRIMARY.value,
        AuthorityLevel.OFFICIAL_GUIDANCE.value,
        AuthorityLevel.APPROVED_COUNSEL.value,
    }
)


class SourceAccessMethod(StrEnum):
    """How a snapshot was obtained. No authenticated scraping is permitted."""

    MANUAL_URL_REGISTRATION = "MANUAL_URL_REGISTRATION"
    PUBLIC_PAGE_FETCH = "PUBLIC_PAGE_FETCH"
    MANUAL_UPLOAD = "MANUAL_UPLOAD"
    NMLS_CHECKLIST_EXPORT = "NMLS_CHECKLIST_EXPORT"
    COUNSEL_DELIVERY = "COUNSEL_DELIVERY"
    VENDOR_DELIVERY = "VENDOR_DELIVERY"
    INTERNAL_AUTHORING = "INTERNAL_AUTHORING"


class SourceVerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    CHANGED_PENDING_REVIEW = "CHANGED_PENDING_REVIEW"
    RETIRED = "RETIRED"


class SnapshotReviewStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RuleSetStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AssessmentType(StrEnum):
    INITIAL_FOOTPRINT = "INITIAL_FOOTPRINT"
    EXPANSION = "EXPANSION"
    PERIODIC_REVIEW = "PERIODIC_REVIEW"
    ACTIVITY_CHANGE = "ACTIVITY_CHANGE"
    SINGLE_JURISDICTION = "SINGLE_JURISDICTION"


class AssessmentStatus(StrEnum):
    DRAFT = "DRAFT"
    EVALUATED = "EVALUATED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    COUNSEL_REVIEW = "COUNSEL_REVIEW"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


#: Only an approved assessment may seed downstream records.
APPROVED_ASSESSMENT_STATUSES: tuple[str, ...] = (AssessmentStatus.APPROVED.value,)


class SourceFreshnessStatus(StrEnum):
    FRESH = "FRESH"
    DUE_FOR_VERIFICATION = "DUE_FOR_VERIFICATION"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    NO_SOURCE = "NO_SOURCE"


class OverrideAuthority(StrEnum):
    COMPLIANCE_MANAGER = "COMPLIANCE_MANAGER"
    INTERNAL_COUNSEL = "INTERNAL_COUNSEL"
    EXTERNAL_COUNSEL = "EXTERNAL_COUNSEL"
    REGULATOR_WRITTEN_GUIDANCE = "REGULATOR_WRITTEN_GUIDANCE"
    EXECUTIVE = "EXECUTIVE"

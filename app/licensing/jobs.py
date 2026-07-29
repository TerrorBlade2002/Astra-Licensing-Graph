"""Durable licensing job enumerations.

Licensing work reuses the established PostgreSQL lease-and-idempotency model
rather than in-process scheduling: nothing long-running may depend only on web
process memory.
"""

from __future__ import annotations

from enum import StrEnum


class LicensingJobType(StrEnum):
    FETCH_REQUIREMENT_SOURCE = "FETCH_REQUIREMENT_SOURCE"
    COMPARE_SOURCE_SNAPSHOT = "COMPARE_SOURCE_SNAPSHOT"
    EVALUATE_REQUIREMENT_ASSESSMENT = "EVALUATE_REQUIREMENT_ASSESSMENT"
    MATERIALIZE_DEADLINES = "MATERIALIZE_DEADLINES"
    CREATE_COMPLIANCE_CASE = "CREATE_COMPLIANCE_CASE"
    CHECK_INFORMATION_FRESHNESS = "CHECK_INFORMATION_FRESHNESS"
    BUILD_DOCUMENT_PACKET = "BUILD_DOCUMENT_PACKET"
    PREPARE_FORM = "PREPARE_FORM"
    GENERATE_FORM_WORKSHEET = "GENERATE_FORM_WORKSHEET"
    CHECK_DOCUMENT_EXPIRY = "CHECK_DOCUMENT_EXPIRY"
    CHECK_LICENSE_RENEWALS = "CHECK_LICENSE_RENEWALS"
    IMPORT_MASTER_TRACKER = "IMPORT_MASTER_TRACKER"
    CREATE_NEXT_OBLIGATION = "CREATE_NEXT_OBLIGATION"


class LicensingJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_REVIEW = "FAILED_REVIEW"
    CANCELLED = "CANCELLED"


ACTIVE_LICENSING_JOB_STATUSES = (
    LicensingJobStatus.PENDING.value,
    LicensingJobStatus.RUNNING.value,
)

#: Named queues so an operator can isolate slow work (packet and form rendering
#: touch SharePoint and PDF libraries) from fast bookkeeping work.
LICENSING_QUEUE_TYPES: dict[str, list[LicensingJobType]] = {
    "licensing": [
        LicensingJobType.CHECK_LICENSE_RENEWALS,
        LicensingJobType.CREATE_COMPLIANCE_CASE,
        LicensingJobType.CREATE_NEXT_OBLIGATION,
        LicensingJobType.CHECK_DOCUMENT_EXPIRY,
    ],
    "requirements": [
        LicensingJobType.FETCH_REQUIREMENT_SOURCE,
        LicensingJobType.COMPARE_SOURCE_SNAPSHOT,
        LicensingJobType.EVALUATE_REQUIREMENT_ASSESSMENT,
    ],
    "deadlines": [
        LicensingJobType.MATERIALIZE_DEADLINES,
        LicensingJobType.CHECK_INFORMATION_FRESHNESS,
    ],
    "packets": [LicensingJobType.BUILD_DOCUMENT_PACKET],
    "forms": [
        LicensingJobType.PREPARE_FORM,
        LicensingJobType.GENERATE_FORM_WORKSHEET,
    ],
    "imports": [LicensingJobType.IMPORT_MASTER_TRACKER],
}


def resolve_licensing_job_types(queues: str) -> list[LicensingJobType]:
    """Map a comma-separated queue list to concrete job types."""
    job_types: list[LicensingJobType] = []
    for queue in queues.split(","):
        name = queue.strip().lower()
        if not name:
            continue
        if name not in LICENSING_QUEUE_TYPES:
            raise SystemExit(
                f"Unknown licensing queue: {name!r} (valid: {sorted(LICENSING_QUEUE_TYPES)})"
            )
        job_types.extend(LICENSING_QUEUE_TYPES[name])
    return job_types or [t for types in LICENSING_QUEUE_TYPES.values() for t in types]

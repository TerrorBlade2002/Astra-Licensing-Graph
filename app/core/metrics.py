"""Prometheus metrics.

Label cardinality is kept deliberately low. Mailbox addresses, subjects,
sender addresses, message IDs, and attachment names are never used as labels.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST as METRICS_CONTENT_TYPE
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

GRAPH_WEBHOOK_REQUESTS_TOTAL = Counter(
    "graph_webhook_requests_total",
    "Webhook HTTP requests received",
    ["endpoint", "outcome"],
    registry=REGISTRY,
)
GRAPH_NOTIFICATIONS_RECEIVED_TOTAL = Counter(
    "graph_notifications_received_total",
    "Individual Graph notifications accepted",
    registry=REGISTRY,
)
GRAPH_NOTIFICATIONS_DUPLICATE_TOTAL = Counter(
    "graph_notifications_duplicate_total",
    "Duplicate Graph notifications",
    registry=REGISTRY,
)
GRAPH_INVALID_CLIENT_STATE_TOTAL = Counter(
    "graph_invalid_client_state_total",
    "Notifications rejected for invalid clientState",
    registry=REGISTRY,
)
GRAPH_UNKNOWN_SUBSCRIPTION_TOTAL = Counter(
    "graph_unknown_subscription_total",
    "Notifications for unknown subscriptions",
    registry=REGISTRY,
)
GRAPH_LIFECYCLE_EVENTS_TOTAL = Counter(
    "graph_lifecycle_events_total",
    "Lifecycle notifications by event",
    ["event"],
    registry=REGISTRY,
)
GRAPH_REQUESTS_TOTAL = Counter(
    "graph_requests_total",
    "Outbound Graph HTTP requests",
    ["method", "outcome"],
    registry=REGISTRY,
)
GRAPH_REQUEST_DURATION_SECONDS = Histogram(
    "graph_request_duration_seconds",
    "Outbound Graph request duration",
    ["operation"],
    registry=REGISTRY,
)
GRAPH_429_TOTAL = Counter("graph_429_total", "Graph throttling responses", registry=REGISTRY)
GRAPH_RETRIES_TOTAL = Counter(
    "graph_retries_total", "Graph request retries", ["reason"], registry=REGISTRY
)
GRAPH_SUBSCRIPTION_EXPIRATION_SECONDS = Gauge(
    "graph_subscription_expiration_seconds",
    "Seconds until the nearest subscription expiry",
    registry=REGISTRY,
)
GRAPH_SUBSCRIPTION_RENEWAL_FAILURES_TOTAL = Counter(
    "graph_subscription_renewal_failures_total",
    "Failed subscription renewals",
    registry=REGISTRY,
)
GRAPH_SYNC_JOBS_TOTAL = Counter(
    "graph_sync_jobs_total", "Folder sync jobs processed", ["outcome"], registry=REGISTRY
)
GRAPH_SYNC_DURATION_SECONDS = Histogram(
    "graph_sync_duration_seconds", "Folder sync round duration", registry=REGISTRY
)
GRAPH_DELTA_PAGES_TOTAL = Counter(
    "graph_delta_pages_total", "Delta pages processed", registry=REGISTRY
)
GRAPH_DELTA_CHANGES_TOTAL = Counter(
    "graph_delta_changes_total", "Delta change entries processed", ["kind"], registry=REGISTRY
)
GRAPH_DELTA_REBASELINE_TOTAL = Counter(
    "graph_delta_rebaseline_total", "Delta rebaselines triggered", registry=REGISTRY
)
GRAPH_INGESTION_JOBS_TOTAL = Counter(
    "graph_ingestion_jobs_total", "Email ingestion jobs processed", ["outcome"], registry=REGISTRY
)
GRAPH_ATTACHMENTS_DOWNLOADED_TOTAL = Counter(
    "graph_attachments_downloaded_total", "Attachments downloaded", registry=REGISTRY
)
GRAPH_ATTACHMENT_BYTES_TOTAL = Counter(
    "graph_attachment_bytes_total", "Attachment bytes downloaded", registry=REGISTRY
)
GRAPH_JOBS_PENDING = Gauge("graph_jobs_pending", "Graph jobs currently pending", registry=REGISTRY)
GRAPH_JOBS_FAILED_REVIEW = Gauge(
    "graph_jobs_failed_review", "Graph jobs in FAILED_REVIEW", registry=REGISTRY
)
GRAPH_WORKER_HEARTBEAT_AGE_SECONDS = Gauge(
    "graph_worker_heartbeat_age_seconds",
    "Age of the freshest worker heartbeat",
    registry=REGISTRY,
)

# SharePoint/document metrics deliberately use no document, filename, path,
# jurisdiction, or license-number labels.
SHAREPOINT_REQUESTS_TOTAL = Counter(
    "sharepoint_requests_total",
    "SharePoint Graph requests",
    ["operation", "outcome"],
    registry=REGISTRY,
)
SHAREPOINT_REQUEST_DURATION_SECONDS = Histogram(
    "sharepoint_request_duration_seconds",
    "SharePoint Graph request duration",
    ["operation"],
    registry=REGISTRY,
)
SHAREPOINT_429_TOTAL = Counter(
    "sharepoint_429_total", "SharePoint throttling responses", registry=REGISTRY
)
SHAREPOINT_RETRIES_TOTAL = Counter(
    "sharepoint_retries_total", "SharePoint request retries", ["reason"], registry=REGISTRY
)
SHAREPOINT_UPLOADS_TOTAL = Counter(
    "sharepoint_uploads_total", "SharePoint uploads", ["method", "outcome"], registry=REGISTRY
)
SHAREPOINT_UPLOAD_BYTES_TOTAL = Counter(
    "sharepoint_upload_bytes_total", "Bytes uploaded to SharePoint", registry=REGISTRY
)
SHAREPOINT_UPLOAD_FAILURES_TOTAL = Counter(
    "sharepoint_upload_failures_total", "Failed SharePoint uploads", registry=REGISTRY
)
SHAREPOINT_UPLOAD_SESSIONS_TOTAL = Counter(
    "sharepoint_upload_sessions_total", "SharePoint upload sessions created", registry=REGISTRY
)
SHAREPOINT_UPLOAD_SESSION_RESTARTS_TOTAL = Counter(
    "sharepoint_upload_session_restarts_total",
    "SharePoint upload session restarts",
    registry=REGISTRY,
)
DOCUMENTS_CREATED_TOTAL = Counter("documents_created_total", "Documents created", registry=REGISTRY)
DOCUMENTS_PROMOTED_TOTAL = Counter(
    "documents_promoted_total", "Attachments promoted", registry=REGISTRY
)
DOCUMENTS_DUPLICATES_TOTAL = Counter(
    "documents_duplicates_total", "Exact document duplicates", registry=REGISTRY
)
DOCUMENTS_APPROVED_TOTAL = Counter(
    "documents_approved_total", "Documents approved", registry=REGISTRY
)
DOCUMENTS_REJECTED_TOTAL = Counter(
    "documents_rejected_total", "Documents rejected", registry=REGISTRY
)
DOCUMENTS_EXPIRING_TOTAL = Counter(
    "documents_expiring_total", "Document expiry observations", ["window"], registry=REGISTRY
)
DOCUMENT_HASH_MISMATCH_TOTAL = Counter(
    "document_hash_mismatch_total", "Document hash mismatches", registry=REGISTRY
)
SHAREPOINT_DELTA_PAGES_TOTAL = Counter(
    "sharepoint_delta_pages_total", "SharePoint delta pages processed", registry=REGISTRY
)
SHAREPOINT_DELTA_CHANGES_TOTAL = Counter(
    "sharepoint_delta_changes_total", "SharePoint delta changes processed", registry=REGISTRY
)
SHAREPOINT_EXTERNAL_DELETIONS_TOTAL = Counter(
    "sharepoint_external_deletions_total", "Externally deleted governed files", registry=REGISTRY
)
DOCUMENT_JOBS_PENDING = Gauge("document_jobs_pending", "Pending document jobs", registry=REGISTRY)
DOCUMENT_JOBS_FAILED_REVIEW = Gauge(
    "document_jobs_failed_review", "Document jobs requiring review", registry=REGISTRY
)

# Controlled communications never label by recipient, subject, Graph ID,
# document filename, task ID, or license number.
COMMUNICATION_RESPONSE_PLANS_TOTAL = Counter(
    "communication_response_plans_total", "Response plans created", registry=REGISTRY
)
COMMUNICATION_DRAFTS_CREATED_TOTAL = Counter(
    "communication_drafts_created_total", "Local drafts created", registry=REGISTRY
)
COMMUNICATION_DRAFT_REVISIONS_TOTAL = Counter(
    "communication_draft_revisions_total", "Immutable draft revisions", registry=REGISTRY
)
COMMUNICATION_DRAFTS_PENDING_REVIEW = Gauge(
    "communication_drafts_pending_review", "Drafts pending content review", registry=REGISTRY
)
COMMUNICATION_DRAFTS_PENDING_SEND_APPROVAL = Gauge(
    "communication_drafts_pending_send_approval", "Drafts pending send approval", registry=REGISTRY
)
COMMUNICATION_DRAFT_VALIDATION_FAILURES_TOTAL = Counter(
    "communication_draft_validation_failures_total", "Draft validation failures", registry=REGISTRY
)
COMMUNICATION_RECIPIENT_POLICY_BLOCKS_TOTAL = Counter(
    "communication_recipient_policy_blocks_total", "Recipient policy blocks", registry=REGISTRY
)
COMMUNICATION_ATTACHMENTS_SELECTED_TOTAL = Counter(
    "communication_attachments_selected_total", "Controlled attachments selected", registry=REGISTRY
)
COMMUNICATION_ATTACHMENT_BYTES_TOTAL = Counter(
    "communication_attachment_bytes_total", "Controlled attachment bytes", registry=REGISTRY
)
COMMUNICATION_SEND_APPROVALS_TOTAL = Counter(
    "communication_send_approvals_total", "Exact-snapshot send approvals", registry=REGISTRY
)
COMMUNICATION_SEND_APPROVALS_INVALIDATED_TOTAL = Counter(
    "communication_send_approvals_invalidated_total",
    "Invalidated send approvals",
    registry=REGISTRY,
)
COMMUNICATION_SEND_JOBS_TOTAL = Counter(
    "communication_send_jobs_total", "Send jobs queued", registry=REGISTRY
)
COMMUNICATION_SEND_ACCEPTED_TOTAL = Counter(
    "communication_send_accepted_total", "Graph send requests accepted", registry=REGISTRY
)
COMMUNICATION_SEND_AMBIGUOUS_TOTAL = Counter(
    "communication_send_ambiguous_total", "Ambiguous send outcomes", registry=REGISTRY
)
COMMUNICATION_SEND_FAILED_REVIEW_TOTAL = Counter(
    "communication_send_failed_review_total", "Sends requiring review", registry=REGISTRY
)
COMMUNICATION_SENT_COPY_VERIFIED_TOTAL = Counter(
    "communication_sent_copy_verified_total", "Sent copies verified", registry=REGISTRY
)
COMMUNICATION_SEND_RECONCILIATION_DURATION_SECONDS = Histogram(
    "communication_send_reconciliation_duration_seconds",
    "Sent-copy reconciliation duration",
    registry=REGISTRY,
)
COMMUNICATION_MOVE_JOBS_TOTAL = Counter(
    "communication_move_jobs_total", "Source move jobs", registry=REGISTRY
)
COMMUNICATION_MOVE_FAILURES_TOTAL = Counter(
    "communication_move_failures_total", "Source move failures", registry=REGISTRY
)
COMMUNICATION_WORKFLOWS_COMPLETED_TOTAL = Counter(
    "communication_workflows_completed_total", "Email workflows completed", registry=REGISTRY
)
COMMUNICATION_OLDEST_PENDING_APPROVAL_AGE_SECONDS = Gauge(
    "communication_oldest_pending_approval_age_seconds",
    "Age of oldest pending send approval",
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Milestone 6: licensing lifecycle, requirements, deadlines, packets, forms.
#
# Legal entity names, license numbers, user names, document filenames, regulator
# names, and case identifiers are never used as labels. Where a dimension is
# genuinely useful it is a low-cardinality closed enum (obligation type, stage,
# outcome) whose value set is fixed by code, not by data.
# ---------------------------------------------------------------------------
LICENSING_INVENTORY_TOTAL = Gauge(
    "licensing_inventory_total", "License inventory records", registry=REGISTRY
)
LICENSING_ACTIVE_LICENSES = Gauge(
    "licensing_active_licenses", "Licenses in an active status", registry=REGISTRY
)
LICENSING_EXPIRING_LICENSES = Gauge(
    "licensing_expiring_licenses",
    "Licenses expiring inside the alert horizon",
    ["window_days"],
    registry=REGISTRY,
)
LICENSING_OVERDUE_OBLIGATIONS = Gauge(
    "licensing_overdue_obligations", "Obligations past their due date", registry=REGISTRY
)

REQUIREMENT_ASSESSMENTS_TOTAL = Counter(
    "requirement_assessments_total", "Requirement assessments created", registry=REGISTRY
)
REQUIREMENT_RESULTS_COUNSEL_REVIEW = Gauge(
    "requirement_results_counsel_review",
    "Requirement results awaiting counsel review",
    registry=REGISTRY,
)
REQUIREMENT_SOURCES_STALE = Gauge(
    "requirement_sources_stale", "Sources past their verification window", registry=REGISTRY
)
REQUIREMENT_SOURCE_CHANGES_PENDING = Gauge(
    "requirement_source_changes_pending",
    "Source snapshots awaiting change review",
    registry=REGISTRY,
)

COMPLIANCE_CASES_OPEN = Gauge(
    "compliance_cases_open", "Compliance cases not yet completed", registry=REGISTRY
)
COMPLIANCE_CASES_BLOCKED = Gauge(
    "compliance_cases_blocked", "Compliance cases blocked", registry=REGISTRY
)
COMPLIANCE_CASES_OVERDUE = Gauge(
    "compliance_cases_overdue", "Compliance cases past due", registry=REGISTRY
)
COMPLIANCE_CASE_STAGE_DURATION_SECONDS = Histogram(
    "compliance_case_stage_duration_seconds",
    "Time a case spent in a stage before transitioning",
    ["stage"],
    buckets=(3600, 21600, 86400, 259200, 604800, 1209600, 2592000, 7776000),
    registry=REGISTRY,
)

DEADLINES_DUE_TOTAL = Gauge(
    "deadlines_due_total", "Open deadlines by type", ["deadline_type"], registry=REGISTRY
)
DEADLINES_OVERDUE_TOTAL = Gauge(
    "deadlines_overdue_total", "Overdue deadlines by type", ["deadline_type"], registry=REGISTRY
)

INFORMATION_REQUESTS_OPEN = Gauge(
    "information_requests_open", "Outstanding internal information requests", registry=REGISTRY
)
INFORMATION_VALUES_STALE = Gauge(
    "information_values_stale", "Approved values past their freshness window", registry=REGISTRY
)

PACKET_BUILDS_TOTAL = Counter(
    "packet_builds_total", "Document packet build attempts", registry=REGISTRY
)
PACKET_MISSING_ITEMS_TOTAL = Counter(
    "packet_missing_items_total", "Packet items that could not be matched", registry=REGISTRY
)

FORM_INSTANCES_TOTAL = Counter("form_instances_total", "Form instances created", registry=REGISTRY)
FORM_FIELDS_MISSING_TOTAL = Counter(
    "form_fields_missing_total", "Form fields lacking approved information", registry=REGISTRY
)
FORMS_WAITING_SIGNATURE = Gauge(
    "forms_waiting_signature", "Form instances awaiting a human signature", registry=REGISTRY
)

TRACKER_IMPORT_ROWS_TOTAL = Counter(
    "tracker_import_rows_total", "Tracker rows processed", ["action"], registry=REGISTRY
)
TRACKER_IMPORT_ERRORS_TOTAL = Counter(
    "tracker_import_errors_total", "Tracker rows that failed", registry=REGISTRY
)

LICENSING_JOBS_TOTAL = Counter(
    "licensing_jobs_total", "Licensing jobs processed", ["job_type", "outcome"], registry=REGISTRY
)


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)


__all__ = [
    "METRICS_CONTENT_TYPE",
    "REGISTRY",
    "render_metrics",
]

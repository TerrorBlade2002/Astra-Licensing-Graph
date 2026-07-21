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


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)


__all__ = [
    "METRICS_CONTENT_TYPE",
    "REGISTRY",
    "render_metrics",
]

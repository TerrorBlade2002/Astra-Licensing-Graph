"""Durable Graph job enumerations."""

from __future__ import annotations

from enum import StrEnum


class JobType(StrEnum):
    ENSURE_SUBSCRIPTION = "ENSURE_SUBSCRIPTION"
    RENEW_SUBSCRIPTION = "RENEW_SUBSCRIPTION"
    RECREATE_SUBSCRIPTION = "RECREATE_SUBSCRIPTION"
    SYNC_FOLDER = "SYNC_FOLDER"
    INGEST_EMAIL = "INGEST_EMAIL"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_REVIEW = "FAILED_REVIEW"
    CANCELLED = "CANCELLED"


# Statuses that count as "active" for coalescing purposes.
ACTIVE_JOB_STATUSES = (JobStatus.PENDING.value, JobStatus.RUNNING.value)

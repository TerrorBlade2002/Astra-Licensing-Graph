"""Typed application configuration loaded from the environment."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AppEnv = Literal["local", "test", "staging", "production"]
AuthMode = Literal["development", "entra"]
LogFormat = Literal["json", "console"]
GraphCredentialMode = Literal["client_secret", "certificate"]
EvidenceBackend = Literal["filesystem", "sharepoint"]
SharePointPermissionMode = Literal["sites_selected", "tenant_wide"]
UploadConflictBehavior = Literal["fail", "rename", "replace-current-version"]
PacketArchiveFormat = Literal["ZIP", "NONE"]

#: List settings read from the environment.
#:
#: ``NoDecode`` stops pydantic-settings from JSON-decoding the raw value before
#: validation. Without it, ``CORS_ORIGINS=https://portal.example.com`` raises a
#: parse error and only JSON array syntax is accepted — so the comma-splitting
#: validator below never saw environment values at all, and a list setting
#: could not be configured outside a constructor call.
StrList = Annotated[list[str], NoDecode]
IntList = Annotated[list[int], NoDecode]

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def _is_loopback(url: str) -> bool:
    """True when a URL (or DSN) resolves to this machine."""
    authority = url.split("://", 1)[-1].split("/", 1)[0]
    host = authority.rsplit("@", 1)[-1].split(":", 1)[0]
    return host in _LOOPBACK_HOSTS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="astra-licensing-automation", alias="APP_NAME")
    app_env: AppEnv = Field(default="local", alias="APP_ENV")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")

    database_url: str = Field(
        default="postgresql+asyncpg://astra:astra_local_dev@localhost:5442/astra_licensing",
        alias="DATABASE_URL",
    )
    database_pool_size: int = Field(default=5, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=10, alias="DATABASE_MAX_OVERFLOW")
    database_pool_recycle_seconds: int = Field(default=1800, alias="DATABASE_POOL_RECYCLE_SECONDS")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: LogFormat = Field(default="json", alias="LOG_FORMAT")
    sql_echo: bool = Field(default=False, alias="SQL_ECHO")

    cors_origins: StrList = Field(default_factory=list, alias="CORS_ORIGINS")

    #: Public addresses of the deployed services. Used for operator diagnostics
    #: and for the deployment checks below; the application never calls them.
    frontend_url: str | None = Field(default=None, alias="FRONTEND_URL")
    backend_url: str | None = Field(default=None, alias="BACKEND_URL")

    auth_mode: AuthMode = Field(default="development", alias="AUTH_MODE")
    entra_tenant_id: str | None = Field(default=None, alias="ENTRA_TENANT_ID")
    entra_api_client_id: str | None = Field(default=None, alias="ENTRA_API_CLIENT_ID")
    entra_api_audience: str | None = Field(default=None, alias="ENTRA_API_AUDIENCE")
    entra_api_scope: str = Field(default="Licensing.Access", alias="ENTRA_API_SCOPE")
    entra_issuer: str | None = Field(default=None, alias="ENTRA_ISSUER")
    entra_openid_configuration_url: str | None = Field(
        default=None, alias="ENTRA_OPENID_CONFIGURATION_URL"
    )
    entra_jwks_cache_seconds: int = Field(default=3600, alias="ENTRA_JWKS_CACHE_SECONDS")
    entra_allowed_algorithms: StrList = Field(
        default_factory=lambda: ["RS256"], alias="ENTRA_ALLOWED_ALGORITHMS"
    )
    entra_clock_skew_seconds: int = Field(default=60, alias="ENTRA_CLOCK_SKEW_SECONDS")
    entra_required_tenant_id: str | None = Field(default=None, alias="ENTRA_REQUIRED_TENANT_ID")

    classification_enabled: bool = Field(default=True, alias="CLASSIFICATION_ENABLED")
    classification_auto_enqueue: bool = Field(default=True, alias="CLASSIFICATION_AUTO_ENQUEUE")
    classification_rule_set: str = Field(default="astra-default", alias="CLASSIFICATION_RULE_SET")
    classification_confidence_review_threshold: float = Field(
        default=0.90, alias="CLASSIFICATION_CONFIDENCE_REVIEW_THRESHOLD"
    )
    classification_review_required: bool = Field(
        default=True, alias="CLASSIFICATION_REVIEW_REQUIRED"
    )
    classification_job_max_attempts: int = Field(default=4, alias="CLASSIFICATION_JOB_MAX_ATTEMPTS")
    classification_body_max_chars: int = Field(
        default=40_000, alias="CLASSIFICATION_BODY_MAX_CHARS"
    )
    classification_quoted_history_max_chars: int = Field(
        default=5_000, alias="CLASSIFICATION_QUOTED_HISTORY_MAX_CHARS"
    )

    ai_classification_enabled: bool = Field(default=False, alias="AI_CLASSIFICATION_ENABLED")
    ai_provider: str = Field(default="openai", alias="AI_PROVIDER")
    ai_external_provider_approved: bool = Field(
        default=False, alias="AI_EXTERNAL_PROVIDER_APPROVED"
    )
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str | None = Field(default=None, alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_timeout_seconds: float = Field(default=30, alias="OPENAI_TIMEOUT_SECONDS")
    openai_max_output_tokens: int = Field(default=1500, alias="OPENAI_MAX_OUTPUT_TOKENS")
    openai_store_responses: bool = Field(default=False, alias="OPENAI_STORE_RESPONSES")
    ai_data_policy_acknowledged: bool = Field(default=False, alias="AI_DATA_POLICY_ACKNOWLEDGED")
    ai_allowed_data_classes: StrList = Field(
        default_factory=lambda: ["licensing_email_sanitized"], alias="AI_ALLOWED_DATA_CLASSES"
    )
    ai_monthly_budget_usd: float = Field(default=0, alias="AI_MONTHLY_BUDGET_USD")
    ai_daily_request_limit: int = Field(default=0, alias="AI_DAILY_REQUEST_LIMIT")

    review_claim_lease_minutes: int = Field(default=30, alias="REVIEW_CLAIM_LEASE_MINUTES")
    review_auto_approval_enabled: bool = Field(default=False, alias="REVIEW_AUTO_APPROVAL_ENABLED")
    review_require_correction_reason: bool = Field(
        default=True, alias="REVIEW_REQUIRE_CORRECTION_REASON"
    )
    review_initial_rollout_mode: bool = Field(default=True, alias="REVIEW_INITIAL_ROLLOUT_MODE")

    # ----------------------------------------------------- Communications M5
    communications_enabled: bool = Field(default=False, alias="COMMUNICATIONS_ENABLED")
    graph_draft_creation_enabled: bool = Field(default=False, alias="GRAPH_DRAFT_CREATION_ENABLED")
    graph_send_enabled: bool = Field(default=False, alias="GRAPH_SEND_ENABLED")
    graph_message_move_enabled: bool = Field(default=False, alias="GRAPH_MESSAGE_MOVE_ENABLED")
    response_ai_drafting_enabled: bool = Field(default=False, alias="RESPONSE_AI_DRAFTING_ENABLED")
    communication_require_send_approval: bool = Field(
        default=True, alias="COMMUNICATION_REQUIRE_SEND_APPROVAL"
    )
    communication_require_separate_send_approver: bool = Field(
        default=True, alias="COMMUNICATION_REQUIRE_SEPARATE_SEND_APPROVER"
    )
    communication_require_two_person_approval: bool = Field(
        default=False, alias="COMMUNICATION_REQUIRE_TWO_PERSON_APPROVAL"
    )
    communication_allow_self_approval: bool = Field(
        default=False, alias="COMMUNICATION_ALLOW_SELF_APPROVAL"
    )
    communication_initial_rollout_mode: bool = Field(
        default=True, alias="COMMUNICATION_INITIAL_ROLLOUT_MODE"
    )
    communication_default_recipient_mode: str = Field(
        default="REPLY", alias="COMMUNICATION_DEFAULT_RECIPIENT_MODE"
    )
    communication_reply_all_enabled: bool = Field(
        default=False, alias="COMMUNICATION_REPLY_ALL_ENABLED"
    )
    communication_reply_all_requires_review: bool = Field(
        default=True, alias="COMMUNICATION_REPLY_ALL_REQUIRES_REVIEW"
    )
    communication_bcc_enabled: bool = Field(default=False, alias="COMMUNICATION_BCC_ENABLED")
    communication_bcc_policy_enabled: bool = Field(
        default=False, alias="COMMUNICATION_BCC_POLICY_ENABLED"
    )
    communication_max_to_recipients: int = Field(default=5, alias="COMMUNICATION_MAX_TO_RECIPIENTS")
    communication_max_cc_recipients: int = Field(
        default=10, alias="COMMUNICATION_MAX_CC_RECIPIENTS"
    )
    communication_max_total_recipients: int = Field(
        default=15, alias="COMMUNICATION_MAX_TOTAL_RECIPIENTS"
    )
    communication_external_recipient_requires_manager: bool = Field(
        default=True, alias="COMMUNICATION_EXTERNAL_RECIPIENT_REQUIRES_MANAGER"
    )
    communication_default_body_format: str = Field(
        default="TEXT", alias="COMMUNICATION_DEFAULT_BODY_FORMAT"
    )
    communication_max_body_chars: int = Field(default=50_000, alias="COMMUNICATION_MAX_BODY_CHARS")
    communication_default_signature_key: str = Field(
        default="licensing-standard", alias="COMMUNICATION_DEFAULT_SIGNATURE_KEY"
    )
    communication_allow_outlook_editing: bool = Field(
        default=True, alias="COMMUNICATION_ALLOW_OUTLOOK_EDITING"
    )
    communication_draft_reconciliation_interval_seconds: int = Field(
        default=60, alias="COMMUNICATION_DRAFT_RECONCILIATION_INTERVAL_SECONDS"
    )
    communication_attachments_enabled: bool = Field(
        default=True, alias="COMMUNICATION_ATTACHMENTS_ENABLED"
    )
    communication_simple_attachment_max_bytes: int = Field(
        default=3_000_000, alias="COMMUNICATION_SIMPLE_ATTACHMENT_MAX_BYTES"
    )
    communication_large_attachments_enabled: bool = Field(
        default=False, alias="COMMUNICATION_LARGE_ATTACHMENTS_ENABLED"
    )
    communication_large_attachment_max_bytes: int = Field(
        default=25_000_000, alias="COMMUNICATION_LARGE_ATTACHMENT_MAX_BYTES"
    )
    communication_total_attachment_max_bytes: int = Field(
        default=20_000_000, alias="COMMUNICATION_TOTAL_ATTACHMENT_MAX_BYTES"
    )
    communication_upload_chunk_bytes: int = Field(
        default=3_276_800, alias="COMMUNICATION_UPLOAD_CHUNK_BYTES"
    )
    communication_shared_mailbox_large_attachment_accepted: bool = Field(
        default=False, alias="COMMUNICATION_SHARED_MAILBOX_LARGE_ATTACHMENT_ACCEPTED"
    )
    communication_send_job_max_attempts: int = Field(
        default=1, alias="COMMUNICATION_SEND_JOB_MAX_ATTEMPTS"
    )
    communication_send_reconciliation_initial_delay_seconds: int = Field(
        default=5, alias="COMMUNICATION_SEND_RECONCILIATION_INITIAL_DELAY_SECONDS"
    )
    communication_send_reconciliation_max_seconds: int = Field(
        default=900, alias="COMMUNICATION_SEND_RECONCILIATION_MAX_SECONDS"
    )
    communication_send_reconciliation_max_attempts: int = Field(
        default=8, alias="COMMUNICATION_SEND_RECONCILIATION_MAX_ATTEMPTS"
    )
    communication_move_policy: str = Field(
        default="TASK_DESTINATION", alias="COMMUNICATION_MOVE_POLICY"
    )
    communication_completed_folder_name: str = Field(
        default="10_Completed", alias="COMMUNICATION_COMPLETED_FOLDER_NAME"
    )
    communication_move_job_max_attempts: int = Field(
        default=4, alias="COMMUNICATION_MOVE_JOB_MAX_ATTEMPTS"
    )
    communication_move_reconciliation_max_attempts: int = Field(
        default=5, alias="COMMUNICATION_MOVE_RECONCILIATION_MAX_ATTEMPTS"
    )

    prototype_import_root: str = Field(default="./prototype-data", alias="PROTOTYPE_IMPORT_ROOT")

    # ------------------------------------------------------------ Graph core
    graph_enabled: bool = Field(default=False, alias="GRAPH_ENABLED")
    #: ``GRAPH_MAILBOX`` is the shorter name used by the Railway variable sets;
    #: both spellings resolve to the single governed licensing mailbox.
    graph_expected_mailbox_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GRAPH_EXPECTED_MAILBOX_ADDRESS", "GRAPH_MAILBOX"),
        serialization_alias="GRAPH_EXPECTED_MAILBOX_ADDRESS",
    )
    graph_base_url: str = Field(default="https://graph.microsoft.com/v1.0", alias="GRAPH_BASE_URL")
    graph_tenant_id: str | None = Field(default=None, alias="GRAPH_TENANT_ID")
    graph_client_id: str | None = Field(default=None, alias="GRAPH_CLIENT_ID")
    graph_scope: str = Field(default="https://graph.microsoft.com/.default", alias="GRAPH_SCOPE")
    graph_credential_mode: GraphCredentialMode = Field(
        default="client_secret", alias="GRAPH_CREDENTIAL_MODE"
    )
    graph_client_secret: str | None = Field(default=None, alias="GRAPH_CLIENT_SECRET")
    graph_certificate_path: str | None = Field(default=None, alias="GRAPH_CERTIFICATE_PATH")
    graph_certificate_thumbprint: str | None = Field(
        default=None, alias="GRAPH_CERTIFICATE_THUMBPRINT"
    )
    graph_token_refresh_skew_seconds: int = Field(
        default=300, alias="GRAPH_TOKEN_REFRESH_SKEW_SECONDS"
    )

    # ----------------------------------------------------------- HTTP client
    graph_connect_timeout_seconds: float = Field(default=10, alias="GRAPH_CONNECT_TIMEOUT_SECONDS")
    graph_read_timeout_seconds: float = Field(default=30, alias="GRAPH_READ_TIMEOUT_SECONDS")
    graph_write_timeout_seconds: float = Field(default=30, alias="GRAPH_WRITE_TIMEOUT_SECONDS")
    graph_pool_timeout_seconds: float = Field(default=10, alias="GRAPH_POOL_TIMEOUT_SECONDS")
    graph_max_connections: int = Field(default=10, alias="GRAPH_MAX_CONNECTIONS")
    graph_max_keepalive_connections: int = Field(default=5, alias="GRAPH_MAX_KEEPALIVE_CONNECTIONS")
    graph_max_retry_attempts: int = Field(default=4, alias="GRAPH_MAX_RETRY_ATTEMPTS")
    graph_max_retry_delay_seconds: float = Field(default=60, alias="GRAPH_MAX_RETRY_DELAY_SECONDS")

    # -------------------------------------------------------------- webhooks
    public_base_url: str = Field(default="http://127.0.0.1:8000", alias="PUBLIC_BASE_URL")
    graph_notification_path: str = Field(
        default="/webhooks/microsoft-graph/messages", alias="GRAPH_NOTIFICATION_PATH"
    )
    graph_lifecycle_path: str = Field(
        default="/webhooks/microsoft-graph/lifecycle", alias="GRAPH_LIFECYCLE_PATH"
    )
    graph_webhook_max_body_bytes: int = Field(default=262_144, alias="GRAPH_WEBHOOK_MAX_BODY_BYTES")
    graph_expected_tenant_id: str | None = Field(default=None, alias="GRAPH_EXPECTED_TENANT_ID")
    graph_allowed_notification_clock_skew_seconds: int = Field(
        default=300, alias="GRAPH_ALLOWED_NOTIFICATION_CLOCK_SKEW_SECONDS"
    )

    # ---------------------------------------------------------- subscriptions
    graph_subscription_lifetime_minutes: int = Field(
        default=8640, alias="GRAPH_SUBSCRIPTION_LIFETIME_MINUTES"
    )
    graph_subscription_renewal_window_minutes: int = Field(
        default=1440, alias="GRAPH_SUBSCRIPTION_RENEWAL_WINDOW_MINUTES"
    )
    graph_subscription_maintenance_interval_seconds: int = Field(
        default=300, alias="GRAPH_SUBSCRIPTION_MAINTENANCE_INTERVAL_SECONDS"
    )
    graph_subscription_change_types: str = Field(
        default="created,updated,deleted", alias="GRAPH_SUBSCRIPTION_CHANGE_TYPES"
    )

    # ------------------------------------------------------------------ delta
    graph_delta_page_size: int = Field(default=50, alias="GRAPH_DELTA_PAGE_SIZE")
    graph_reconciliation_interval_seconds: int = Field(
        default=300, alias="GRAPH_RECONCILIATION_INTERVAL_SECONDS"
    )
    graph_delta_select_fields: str = Field(
        default=(
            "id,subject,from,toRecipients,ccRecipients,receivedDateTime,bodyPreview,"
            "hasAttachments,conversationId,internetMessageId,isRead,parentFolderId,"
            "lastModifiedDateTime"
        ),
        alias="GRAPH_DELTA_SELECT_FIELDS",
    )

    # ---------------------------------------------------------------- workers
    graph_worker_id: str | None = Field(default=None, alias="GRAPH_WORKER_ID")
    graph_worker_poll_interval_seconds: float = Field(
        default=2.0, alias="GRAPH_WORKER_POLL_INTERVAL_SECONDS"
    )
    graph_job_lease_seconds: int = Field(default=120, alias="GRAPH_JOB_LEASE_SECONDS")
    graph_job_max_attempts: int = Field(default=6, alias="GRAPH_JOB_MAX_ATTEMPTS")
    graph_job_retry_base_seconds: float = Field(default=5, alias="GRAPH_JOB_RETRY_BASE_SECONDS")
    graph_job_retry_max_seconds: float = Field(default=900, alias="GRAPH_JOB_RETRY_MAX_SECONDS")
    graph_job_heartbeat_interval_seconds: int = Field(
        default=30, alias="GRAPH_JOB_HEARTBEAT_INTERVAL_SECONDS"
    )

    # --------------------------------------------------------------- evidence
    evidence_storage_backend: EvidenceBackend = Field(
        default="filesystem", alias="EVIDENCE_STORAGE_BACKEND"
    )
    filesystem_evidence_root: str = Field(default="./evidence", alias="FILESYSTEM_EVIDENCE_ROOT")
    max_raw_mime_bytes: int = Field(default=26_214_400, alias="MAX_RAW_MIME_BYTES")
    max_attachment_bytes: int = Field(default=26_214_400, alias="MAX_ATTACHMENT_BYTES")
    max_attachments_per_message: int = Field(default=25, alias="MAX_ATTACHMENTS_PER_MESSAGE")
    allowed_attachment_mime_types: StrList = Field(
        default_factory=lambda: [
            "application/pdf",
            "text/csv",
            "text/plain",
            "image/png",
            "image/jpeg",
            "image/gif",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/msword",
            "application/vnd.ms-excel",
            "application/zip",
            "application/octet-stream",
            "message/rfc822",
        ],
        alias="ALLOWED_ATTACHMENT_MIME_TYPES",
    )
    quarantine_unknown_attachments: bool = Field(
        default=True, alias="QUARANTINE_UNKNOWN_ATTACHMENTS"
    )

    # ------------------------------------------------------------ SharePoint
    sharepoint_enabled: bool = Field(default=False, alias="SHAREPOINT_ENABLED")
    sharepoint_site_id: str | None = Field(default=None, alias="SHAREPOINT_SITE_ID")
    sharepoint_site_hostname: str | None = Field(default=None, alias="SHAREPOINT_SITE_HOSTNAME")
    sharepoint_site_path: str | None = Field(default=None, alias="SHAREPOINT_SITE_PATH")
    sharepoint_site_web_url: str | None = Field(default=None, alias="SHAREPOINT_SITE_WEB_URL")
    sharepoint_permission_mode: SharePointPermissionMode = Field(
        default="sites_selected", alias="SHAREPOINT_PERMISSION_MODE"
    )
    sharepoint_expected_app_id: str | None = Field(default=None, alias="SHAREPOINT_EXPECTED_APP_ID")
    sharepoint_negative_test_site_id: str | None = Field(
        default=None, alias="SHAREPOINT_NEGATIVE_TEST_SITE_ID"
    )
    sharepoint_enable_write_health_check: bool = Field(
        default=False, alias="SHAREPOINT_ENABLE_WRITE_HEALTH_CHECK"
    )

    sharepoint_master_documents_drive_id: str | None = Field(
        default=None, alias="SHAREPOINT_MASTER_DOCUMENTS_DRIVE_ID"
    )
    sharepoint_working_documents_drive_id: str | None = Field(
        default=None, alias="SHAREPOINT_WORKING_DOCUMENTS_DRIVE_ID"
    )
    sharepoint_bonds_drive_id: str | None = Field(default=None, alias="SHAREPOINT_BONDS_DRIVE_ID")
    sharepoint_submitted_filings_drive_id: str | None = Field(
        default=None, alias="SHAREPOINT_SUBMITTED_FILINGS_DRIVE_ID"
    )
    sharepoint_licenses_drive_id: str | None = Field(
        default=None, alias="SHAREPOINT_LICENSES_DRIVE_ID"
    )
    sharepoint_correspondence_drive_id: str | None = Field(
        default=None, alias="SHAREPOINT_CORRESPONDENCE_DRIVE_ID"
    )
    sharepoint_payments_drive_id: str | None = Field(
        default=None, alias="SHAREPOINT_PAYMENTS_DRIVE_ID"
    )
    sharepoint_forms_drive_id: str | None = Field(default=None, alias="SHAREPOINT_FORMS_DRIVE_ID")
    sharepoint_quarantine_drive_id: str | None = Field(
        default=None, alias="SHAREPOINT_QUARANTINE_DRIVE_ID"
    )

    sharepoint_simple_upload_max_bytes: int = Field(
        default=4 * 1024 * 1024, alias="SHAREPOINT_SIMPLE_UPLOAD_MAX_BYTES"
    )
    sharepoint_upload_session_threshold_bytes: int = Field(
        default=4 * 1024 * 1024, alias="SHAREPOINT_UPLOAD_SESSION_THRESHOLD_BYTES"
    )
    sharepoint_upload_chunk_bytes: int = Field(
        default=5 * 1024 * 1024, alias="SHAREPOINT_UPLOAD_CHUNK_BYTES"
    )
    sharepoint_upload_max_attempts: int = Field(default=5, alias="SHAREPOINT_UPLOAD_MAX_ATTEMPTS")
    sharepoint_upload_session_expiry_skew_seconds: int = Field(
        default=120, alias="SHAREPOINT_UPLOAD_SESSION_EXPIRY_SKEW_SECONDS"
    )
    sharepoint_upload_conflict_behavior: UploadConflictBehavior = Field(
        default="fail", alias="SHAREPOINT_UPLOAD_CONFLICT_BEHAVIOR"
    )
    sharepoint_upload_timeout_seconds: float = Field(
        default=120, alias="SHAREPOINT_UPLOAD_TIMEOUT_SECONDS"
    )

    document_max_bytes: int = Field(default=100 * 1024 * 1024, alias="DOCUMENT_MAX_BYTES")
    document_allowed_mime_types: StrList = Field(
        default_factory=lambda: [
            "application/pdf",
            "image/png",
            "image/jpeg",
            "text/plain",
            "text/csv",
            "application/msword",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ],
        alias="DOCUMENT_ALLOWED_MIME_TYPES",
    )
    document_allowed_extensions: StrList = Field(
        default_factory=lambda: [
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".txt",
            ".csv",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
        ],
        alias="DOCUMENT_ALLOWED_EXTENSIONS",
    )
    document_quarantine_unknown_types: bool = Field(
        default=True, alias="DOCUMENT_QUARANTINE_UNKNOWN_TYPES"
    )
    document_require_sha256: bool = Field(default=True, alias="DOCUMENT_REQUIRE_SHA256")
    document_duplicate_policy: str = Field(
        default="link_existing", alias="DOCUMENT_DUPLICATE_POLICY"
    )
    document_filename_max_length: int = Field(default=180, alias="DOCUMENT_FILENAME_MAX_LENGTH")
    document_download_max_bytes: int = Field(
        default=100 * 1024 * 1024, alias="DOCUMENT_DOWNLOAD_MAX_BYTES"
    )
    document_preview_enabled: bool = Field(default=False, alias="DOCUMENT_PREVIEW_ENABLED")
    document_expiry_alert_days: IntList = Field(
        default_factory=lambda: [120, 90, 60, 30, 14, 7, 0], alias="DOCUMENT_EXPIRY_ALERT_DAYS"
    )

    sharepoint_reconciliation_interval_seconds: int = Field(
        default=900, alias="SHAREPOINT_RECONCILIATION_INTERVAL_SECONDS"
    )
    sharepoint_delta_page_size: int = Field(default=200, alias="SHAREPOINT_DELTA_PAGE_SIZE")
    sharepoint_full_reconciliation_interval_hours: int = Field(
        default=24, alias="SHAREPOINT_FULL_RECONCILIATION_INTERVAL_HOURS"
    )
    sharepoint_missing_item_grace_hours: int = Field(
        default=24, alias="SHAREPOINT_MISSING_ITEM_GRACE_HOURS"
    )

    # ------------------------------------------------------------------
    # Milestone 6: licensing lifecycle, requirement matrix, deadlines,
    # reusable information, packets, forms, and controlled imports.
    # ------------------------------------------------------------------
    licensing_enabled: bool = Field(default=True, alias="LICENSING_ENABLED")
    licensing_default_lead_days: int = Field(default=30, alias="LICENSING_DEFAULT_LEAD_DAYS")
    licensing_planning_horizon_days: int = Field(
        default=540, alias="LICENSING_PLANNING_HORIZON_DAYS"
    )
    licensing_requirement_matrix_enabled: bool = Field(
        default=True, alias="LICENSING_REQUIREMENT_MATRIX_ENABLED"
    )
    #: Human review of every advisory requirement result. Never disable in
    #: production: the matrix is advisory and must not stand as a legal answer.
    licensing_require_human_review: bool = Field(
        default=True, alias="LICENSING_REQUIRE_HUMAN_REVIEW"
    )
    licensing_require_counsel_for_not_required: bool = Field(
        default=True, alias="LICENSING_REQUIRE_COUNSEL_FOR_NOT_REQUIRED"
    )
    licensing_default_timezone: str = Field(
        default="America/New_York", alias="LICENSING_DEFAULT_TIMEZONE"
    )
    #: Global cross-entity reuse switch. Must stay false; reuse is granted
    #: per value through an explicit approval record instead.
    licensing_cross_entity_reuse_enabled: bool = Field(
        default=False, alias="LICENSING_CROSS_ENTITY_REUSE_ENABLED"
    )
    #: Guards against the matrix ever being presented as legal advice.
    licensing_matrix_advisory_only: bool = Field(
        default=True, alias="LICENSING_MATRIX_ADVISORY_ONLY"
    )
    licensing_job_lease_seconds: int = Field(default=300, alias="LICENSING_JOB_LEASE_SECONDS")
    licensing_worker_poll_interval_seconds: float = Field(
        default=5.0, alias="LICENSING_WORKER_POLL_INTERVAL_SECONDS"
    )

    requirement_source_fetch_enabled: bool = Field(
        default=False, alias="REQUIREMENT_SOURCE_FETCH_ENABLED"
    )
    requirement_source_max_bytes: int = Field(
        default=25 * 1024 * 1024, alias="REQUIREMENT_SOURCE_MAX_BYTES"
    )
    #: Explicit allow-list of public regulator hosts. Authenticated portals
    #: (NMLS sign-in, state licensee portals) must never appear here.
    requirement_source_allowed_hosts: StrList = Field(
        default_factory=list, alias="REQUIREMENT_SOURCE_ALLOWED_HOSTS"
    )
    requirement_source_freshness_days: int = Field(
        default=365, alias="REQUIREMENT_SOURCE_FRESHNESS_DAYS"
    )
    requirement_source_change_review_required: bool = Field(
        default=True, alias="REQUIREMENT_SOURCE_CHANGE_REVIEW_REQUIRED"
    )
    requirement_source_fetch_timeout_seconds: float = Field(
        default=30.0, alias="REQUIREMENT_SOURCE_FETCH_TIMEOUT_SECONDS"
    )

    deadline_materialization_interval_seconds: int = Field(
        default=3600, alias="DEADLINE_MATERIALIZATION_INTERVAL_SECONDS"
    )
    deadline_alert_windows_days: IntList = Field(
        default_factory=lambda: [120, 90, 60, 30, 14, 7, 3, 0],
        alias="DEADLINE_ALERT_WINDOWS_DAYS",
    )
    deadline_overdue_escalation_enabled: bool = Field(
        default=True, alias="DEADLINE_OVERDUE_ESCALATION_ENABLED"
    )

    information_registry_enabled: bool = Field(default=True, alias="INFORMATION_REGISTRY_ENABLED")
    #: Operational pointer to the vault/KMS entry holding the keys. The key
    #: material itself is read from INFORMATION_ENCRYPTION_KEYS at use time and
    #: never stored in settings.
    information_encryption_key_reference: str | None = Field(
        default=None, alias="INFORMATION_ENCRYPTION_KEY_REFERENCE"
    )
    information_default_freshness_days: int = Field(
        default=365, alias="INFORMATION_DEFAULT_FRESHNESS_DAYS"
    )
    information_highly_restricted_enabled: bool = Field(
        default=False, alias="INFORMATION_HIGHLY_RESTRICTED_ENABLED"
    )

    packet_generation_enabled: bool = Field(default=True, alias="PACKET_GENERATION_ENABLED")
    packet_max_documents: int = Field(default=100, alias="PACKET_MAX_DOCUMENTS")
    packet_max_total_bytes: int = Field(default=250 * 1024 * 1024, alias="PACKET_MAX_TOTAL_BYTES")
    packet_include_cover_sheet: bool = Field(default=True, alias="PACKET_INCLUDE_COVER_SHEET")
    packet_archive_format: PacketArchiveFormat = Field(default="ZIP", alias="PACKET_ARCHIVE_FORMAT")

    form_preparation_enabled: bool = Field(default=True, alias="FORM_PREPARATION_ENABLED")
    form_max_template_bytes: int = Field(default=50 * 1024 * 1024, alias="FORM_MAX_TEMPLATE_BYTES")
    form_pdf_filling_enabled: bool = Field(default=True, alias="FORM_PDF_FILLING_ENABLED")
    form_docx_filling_enabled: bool = Field(default=True, alias="FORM_DOCX_FILLING_ENABLED")
    form_flat_pdf_worksheet_enabled: bool = Field(
        default=True, alias="FORM_FLAT_PDF_WORKSHEET_ENABLED"
    )
    #: Hard boundaries for Milestone 6. Production startup fails if either is on.
    form_signature_automation_enabled: bool = Field(
        default=False, alias="FORM_SIGNATURE_AUTOMATION_ENABLED"
    )
    form_external_submission_enabled: bool = Field(
        default=False, alias="FORM_EXTERNAL_SUBMISSION_ENABLED"
    )
    #: Flattening a filled PDF is only allowed as an explicit post-approval step.
    form_flatten_after_approval_enabled: bool = Field(
        default=False, alias="FORM_FLATTEN_AFTER_APPROVAL_ENABLED"
    )
    form_download_ttl_seconds: int = Field(default=300, alias="FORM_DOWNLOAD_TTL_SECONDS")

    tracker_import_enabled: bool = Field(default=True, alias="TRACKER_IMPORT_ENABLED")
    tracker_import_max_bytes: int = Field(
        default=25 * 1024 * 1024, alias="TRACKER_IMPORT_MAX_BYTES"
    )
    tracker_import_allowed_extensions: StrList = Field(
        default_factory=lambda: [".xlsx", ".csv"], alias="TRACKER_IMPORT_ALLOWED_EXTENSIONS"
    )
    tracker_import_max_rows: int = Field(default=20000, alias="TRACKER_IMPORT_MAX_ROWS")

    # ------------------------------------------------ Portal assistance M7
    portal_automation_enabled: bool = Field(default=False, alias="PORTAL_AUTOMATION_ENABLED")
    portal_allowed_hosts: StrList = Field(default_factory=list, alias="PORTAL_ALLOWED_HOSTS")
    portal_require_active_review: bool = Field(default=True, alias="PORTAL_REQUIRE_ACTIVE_REVIEW")
    portal_default_automation_level: str = Field(
        default="PREPARE_ONLY", alias="PORTAL_DEFAULT_AUTOMATION_LEVEL"
    )
    portal_terms_review_max_age_days: int = Field(
        default=365, alias="PORTAL_TERMS_REVIEW_MAX_AGE_DAYS"
    )

    browser_automation_enabled: bool = Field(default=False, alias="BROWSER_AUTOMATION_ENABLED")
    browser_type: Literal["chromium"] = Field(default="chromium", alias="BROWSER_TYPE")
    browser_headless: bool = Field(default=True, alias="BROWSER_HEADLESS")
    browser_worker_pool_size: int = Field(default=1, alias="BROWSER_WORKER_POOL_SIZE")
    browser_session_max_minutes: int = Field(default=60, alias="BROWSER_SESSION_MAX_MINUTES")
    browser_inactivity_timeout_minutes: int = Field(
        default=15, alias="BROWSER_INACTIVITY_TIMEOUT_MINUTES"
    )
    browser_navigation_timeout_seconds: int = Field(
        default=30, alias="BROWSER_NAVIGATION_TIMEOUT_SECONDS"
    )
    browser_action_timeout_seconds: int = Field(default=10, alias="BROWSER_ACTION_TIMEOUT_SECONDS")
    browser_temp_root: str = Field(default="/tmp/astra-portals", alias="BROWSER_TEMP_ROOT")
    browser_session_state_persistence: bool = Field(
        default=False, alias="BROWSER_SESSION_STATE_PERSISTENCE"
    )
    browser_session_encryption_key_reference: str | None = Field(
        default=None, alias="BROWSER_SESSION_ENCRYPTION_KEY_REFERENCE"
    )
    browser_screenshot_enabled: bool = Field(default=False, alias="BROWSER_SCREENSHOT_ENABLED")
    browser_video_enabled: bool = Field(default=False, alias="BROWSER_VIDEO_ENABLED")
    browser_remote_debugging_url: str | None = Field(
        default=None, alias="BROWSER_REMOTE_DEBUGGING_URL"
    )

    portal_login_human_only: bool = Field(default=True, alias="PORTAL_LOGIN_HUMAN_ONLY")
    portal_mfa_human_only: bool = Field(default=True, alias="PORTAL_MFA_HUMAN_ONLY")
    portal_captcha_human_only: bool = Field(default=True, alias="PORTAL_CAPTCHA_HUMAN_ONLY")
    portal_terms_acceptance_human_only: bool = Field(
        default=True, alias="PORTAL_TERMS_ACCEPTANCE_HUMAN_ONLY"
    )
    portal_attestation_human_only: bool = Field(default=True, alias="PORTAL_ATTESTATION_HUMAN_ONLY")
    portal_signature_human_only: bool = Field(default=True, alias="PORTAL_SIGNATURE_HUMAN_ONLY")
    portal_payment_human_only: bool = Field(default=True, alias="PORTAL_PAYMENT_HUMAN_ONLY")
    portal_final_submit_human_only: bool = Field(
        default=True, alias="PORTAL_FINAL_SUBMIT_HUMAN_ONLY"
    )
    portal_captcha_solving_enabled: bool = Field(
        default=False, alias="PORTAL_CAPTCHA_SOLVING_ENABLED"
    )
    portal_mfa_bypass_enabled: bool = Field(default=False, alias="PORTAL_MFA_BYPASS_ENABLED")

    portal_upload_max_files: int = Field(default=50, alias="PORTAL_UPLOAD_MAX_FILES")
    portal_upload_max_total_bytes: int = Field(
        default=250 * 1024 * 1024, alias="PORTAL_UPLOAD_MAX_TOTAL_BYTES"
    )
    portal_upload_allowed_mime_types: StrList = Field(
        default_factory=lambda: [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ],
        alias="PORTAL_UPLOAD_ALLOWED_MIME_TYPES",
    )
    portal_capture_screenshots: bool = Field(default=False, alias="PORTAL_CAPTURE_SCREENSHOTS")
    portal_capture_dom_snapshots: bool = Field(default=True, alias="PORTAL_CAPTURE_DOM_SNAPSHOTS")
    portal_capture_pre_submission_pdf: bool = Field(
        default=False, alias="PORTAL_CAPTURE_PRE_SUBMISSION_PDF"
    )
    portal_evidence_redaction_enabled: bool = Field(
        default=True, alias="PORTAL_EVIDENCE_REDACTION_ENABLED"
    )
    portal_job_lease_seconds: int = Field(default=120, alias="PORTAL_JOB_LEASE_SECONDS")
    portal_worker_poll_interval_seconds: float = Field(
        default=2.0, alias="PORTAL_WORKER_POLL_INTERVAL_SECONDS"
    )

    @field_validator(
        "cors_origins",
        "entra_allowed_algorithms",
        "ai_allowed_data_classes",
        "allowed_attachment_mime_types",
        "document_allowed_mime_types",
        "document_allowed_extensions",
        "document_expiry_alert_days",
        "requirement_source_allowed_hosts",
        "deadline_alert_windows_days",
        "tracker_import_allowed_extensions",
        "portal_allowed_hosts",
        "portal_upload_allowed_mime_types",
        mode="before",
    )
    @classmethod
    def _split_comma_lists(cls, value: object) -> object:
        """Accept ``a,b`` and ``["a","b"]`` for every list setting.

        Both forms appear in real variable sets — a JSON array is natural when
        an entry contains a comma, a plain list is natural everywhere else — and
        a deployment should not fail over the difference.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"value looks like JSON but does not parse: {exc.msg}") from exc
        return [item.strip() for item in text.split(",") if item.strip()]

    @field_validator("graph_base_url")
    @classmethod
    def _graph_base_url_must_be_https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("GRAPH_BASE_URL must use HTTPS")
        return value.rstrip("/")

    @field_validator("database_url")
    @classmethod
    def _require_postgresql(cls, value: str) -> str:
        if not value.startswith(("postgresql+asyncpg://", "postgresql://")):
            raise ValueError("DATABASE_URL must point at PostgreSQL (postgresql+asyncpg://...)")
        return value

    @model_validator(mode="after")
    def _reject_unsafe_production_settings(self) -> Self:
        problems: list[str] = []
        if self.graph_send_enabled and not self.communication_require_send_approval:
            problems.append("GRAPH_SEND_ENABLED requires explicit send approval")
        if self.communication_initial_rollout_mode and self.communication_allow_self_approval:
            problems.append("self send approval is forbidden during initial rollout")
        if self.graph_send_enabled and not self.graph_expected_mailbox_address:
            problems.append("Mail.Send requires GRAPH_EXPECTED_MAILBOX_ADDRESS")
        if self.communication_large_attachments_enabled and not (
            self.communication_shared_mailbox_large_attachment_accepted
        ):
            problems.append("large shared-mailbox attachments require staging acceptance")
        if self.communication_bcc_enabled and not self.communication_bcc_policy_enabled:
            problems.append("BCC requires an explicit approved policy")
        if self.communication_reply_all_enabled and not (
            self.communication_reply_all_requires_review
        ):
            problems.append("reply-all requires explicit recipient review")
        if self.communication_move_policy not in {"TASK_DESTINATION", "COMPLETED_FOLDER"}:
            problems.append("communication move policy is invalid")
        if self.communication_default_recipient_mode not in {
            "REPLY",
            "REPLY_ALL",
            "MANUAL",
            "INTERNAL_FORWARD",
            "NONE",
        }:
            problems.append("default communication recipient mode is invalid")
        if self.communication_default_body_format not in {"TEXT", "HTML"}:
            problems.append("default communication body format is invalid")
        if (
            min(
                self.communication_simple_attachment_max_bytes,
                self.communication_large_attachment_max_bytes,
                self.communication_total_attachment_max_bytes,
                self.communication_upload_chunk_bytes,
            )
            <= 0
        ):
            problems.append("communication attachment limits must be positive")
        if (
            self.communication_simple_attachment_max_bytes
            > self.communication_large_attachment_max_bytes
        ):
            problems.append("simple attachment limit cannot exceed the large attachment limit")
        if (
            self.communication_total_attachment_max_bytes
            > self.communication_large_attachment_max_bytes
        ):
            problems.append("total attachment limit cannot exceed the large attachment limit")
        if self.communication_upload_chunk_bytes % (320 * 1024) != 0:
            problems.append("communication upload chunks must be a multiple of 320 KiB")
        if self.response_ai_drafting_enabled:
            if not self.ai_external_provider_approved or not self.ai_data_policy_acknowledged:
                problems.append(
                    "AI response drafting requires external-provider approval "
                    "and data-policy acknowledgement"
                )
            if not self.openai_api_key or not self.openai_model:
                problems.append("AI response drafting requires OPENAI_API_KEY and OPENAI_MODEL")
            if "licensing_response_sanitized" not in self.ai_allowed_data_classes:
                problems.append(
                    "AI response drafting requires licensing_response_sanitized "
                    "in AI_ALLOWED_DATA_CLASSES"
                )
            if self.openai_store_responses:
                problems.append("OPENAI_STORE_RESPONSES must remain false for response drafting")
        if self.app_env == "production":
            if self.auth_mode == "development":
                problems.append("AUTH_MODE=development is not allowed in production")
            if not self.entra_tenant_id or not self.entra_api_audience:
                problems.append("production Entra authentication requires tenant and audience")
            if self.review_auto_approval_enabled or not self.classification_review_required:
                problems.append(
                    "production initial rollout requires human review and disables auto approval"
                )
            if self.sql_echo:
                problems.append("SQL_ECHO must be disabled in production")
            if "*" in self.cors_origins:
                problems.append("CORS_ORIGINS must not contain '*' in production")
            if self.evidence_storage_backend == "filesystem":
                problems.append("EVIDENCE_STORAGE_BACKEND=filesystem is not allowed in production")
            if self.evidence_storage_backend == "sharepoint" and not self.sharepoint_enabled:
                problems.append("EVIDENCE_STORAGE_BACKEND=sharepoint requires SHAREPOINT_ENABLED")
            if self.sharepoint_enabled:
                if self.sharepoint_permission_mode != "sites_selected":
                    problems.append(
                        "production SharePoint requires SHAREPOINT_PERMISSION_MODE=sites_selected"
                    )
                if not self.sharepoint_site_id:
                    problems.append("production SharePoint requires explicit SHAREPOINT_SITE_ID")
                if not self.sharepoint_expected_app_id:
                    problems.append("production SharePoint requires SHAREPOINT_EXPECTED_APP_ID")
                if not self.sharepoint_quarantine_drive_id:
                    problems.append("production SharePoint requires a quarantine drive")
                if not all(self.sharepoint_drive_ids.values()):
                    problems.append("all production SharePoint drive IDs must be explicit")
            if self.communications_enabled and self.auth_mode == "development":
                problems.append("production communications cannot use development authentication")
            if self.graph_message_move_enabled and self.communication_move_policy not in {
                "TASK_DESTINATION",
                "COMPLETED_FOLDER",
            }:
                problems.append("automatic move requires a verified move policy")
        if self.app_env not in ("local", "test"):
            host = self.public_base_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
            if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                problems.append("PUBLIC_BASE_URL must not point at localhost outside local/test")
            if not self.public_base_url.startswith("https://"):
                problems.append("PUBLIC_BASE_URL must use HTTPS outside local/test")
        if self.graph_enabled:
            if not self.graph_tenant_id or not self.graph_client_id:
                problems.append("GRAPH_ENABLED requires GRAPH_TENANT_ID and GRAPH_CLIENT_ID")
            if self.graph_credential_mode == "client_secret" and not self.graph_client_secret:
                problems.append("GRAPH_CREDENTIAL_MODE=client_secret requires GRAPH_CLIENT_SECRET")
            if self.graph_credential_mode == "certificate" and (
                not self.graph_certificate_path or not self.graph_certificate_thumbprint
            ):
                problems.append(
                    "GRAPH_CREDENTIAL_MODE=certificate requires GRAPH_CERTIFICATE_PATH "
                    "and GRAPH_CERTIFICATE_THUMBPRINT"
                )
        if self.sharepoint_enabled:
            if not self.graph_enabled:
                problems.append("SHAREPOINT_ENABLED requires GRAPH_ENABLED")
            if not self.sharepoint_site_id and not (
                self.sharepoint_site_hostname and self.sharepoint_site_path
            ):
                problems.append(
                    "SHAREPOINT_ENABLED requires SHAREPOINT_SITE_ID or hostname and site path"
                )
            if self.sharepoint_upload_chunk_bytes < 320 * 1024:
                problems.append("SHAREPOINT_UPLOAD_CHUNK_BYTES must be at least 320 KiB")
            if self.sharepoint_upload_chunk_bytes % (320 * 1024) != 0:
                problems.append("SHAREPOINT_UPLOAD_CHUNK_BYTES must be a multiple of 320 KiB")
        if self.auth_mode == "entra" and (not self.entra_tenant_id or not self.entra_api_audience):
            problems.append("AUTH_MODE=entra requires ENTRA_TENANT_ID and ENTRA_API_AUDIENCE")
        if self.ai_classification_enabled:
            if not self.ai_external_provider_approved or not self.ai_data_policy_acknowledged:
                problems.append(
                    "AI classification requires external-provider approval "
                    "and data-policy acknowledgement"
                )
            if not self.openai_api_key or not self.openai_model:
                problems.append("AI classification requires OPENAI_API_KEY and OPENAI_MODEL")
            if self.openai_store_responses:
                problems.append("OPENAI_STORE_RESPONSES must remain false for Milestone 4")
        problems.extend(self._licensing_problems())
        problems.extend(self._portal_problems())
        problems.extend(self._deployment_problems())
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def _licensing_problems(self) -> list[str]:
        """Milestone 6 safety rails.

        Two classes of rule live here. The first applies everywhere, because a
        setting like "signature automation" has no legitimate value in any
        environment during Milestone 6. The second applies only to production,
        where a development-grade shortcut becomes a compliance failure.
        """
        problems: list[str] = []

        # Absolute Milestone 6 boundaries, enforced in every environment.
        if self.form_signature_automation_enabled:
            problems.append(
                "FORM_SIGNATURE_AUTOMATION_ENABLED must remain false: Milestone 6 records "
                "that a signature is required and never applies one"
            )
        if self.form_external_submission_enabled:
            problems.append(
                "FORM_EXTERNAL_SUBMISSION_ENABLED must remain false: Milestone 6 prepares "
                "filings but never submits them"
            )
        if not self.licensing_matrix_advisory_only:
            problems.append(
                "LICENSING_MATRIX_ADVISORY_ONLY must remain true: requirement results are "
                "advisory and must not be presented as legal advice"
            )

        # Internal consistency, independent of environment.
        if self.licensing_default_lead_days < 0:
            problems.append("LICENSING_DEFAULT_LEAD_DAYS cannot be negative")
        if self.licensing_planning_horizon_days <= 0:
            problems.append("LICENSING_PLANNING_HORIZON_DAYS must be positive")
        if self.licensing_planning_horizon_days < self.licensing_default_lead_days:
            problems.append(
                "LICENSING_PLANNING_HORIZON_DAYS must cover LICENSING_DEFAULT_LEAD_DAYS"
            )
        if any(window < 0 for window in self.deadline_alert_windows_days):
            problems.append("DEADLINE_ALERT_WINDOWS_DAYS must not contain negative values")
        if self.packet_max_documents <= 0 or self.packet_max_total_bytes <= 0:
            problems.append("packet size limits must be positive")
        if self.form_max_template_bytes <= 0:
            problems.append("FORM_MAX_TEMPLATE_BYTES must be positive")
        if self.tracker_import_max_bytes <= 0 or self.tracker_import_max_rows <= 0:
            problems.append("tracker import limits must be positive")
        if any(
            not extension.startswith(".") for extension in self.tracker_import_allowed_extensions
        ):
            problems.append("TRACKER_IMPORT_ALLOWED_EXTENSIONS entries must start with '.'")
        # Macro-enabled and legacy binary workbooks are never parsed.
        rejected = {".xlsm", ".xltm", ".xlsb", ".xls"}
        if rejected & {ext.lower() for ext in self.tracker_import_allowed_extensions}:
            problems.append(
                "macro-enabled or legacy binary spreadsheet extensions cannot be imported"
            )
        if self.requirement_source_fetch_enabled and not self.requirement_source_allowed_hosts:
            problems.append(
                "REQUIREMENT_SOURCE_FETCH_ENABLED requires an explicit "
                "REQUIREMENT_SOURCE_ALLOWED_HOSTS allow-list"
            )
        if self.form_flatten_after_approval_enabled and not self.form_pdf_filling_enabled:
            problems.append("PDF flattening requires FORM_PDF_FILLING_ENABLED")

        if self.app_env != "production":
            return problems

        # Production-only requirements.
        if not self.licensing_require_human_review:
            problems.append(
                "production requires LICENSING_REQUIRE_HUMAN_REVIEW: an unreviewed "
                "requirement result must never stand as a determination"
            )
        if not self.requirement_source_change_review_required:
            problems.append(
                "production requires REQUIREMENT_SOURCE_CHANGE_REVIEW_REQUIRED so a changed "
                "source cannot silently alter active rules"
            )
        if self.information_registry_enabled and not self.information_encryption_key_reference:
            problems.append(
                "production requires INFORMATION_ENCRYPTION_KEY_REFERENCE for sensitive "
                "reusable information"
            )
        if self.licensing_cross_entity_reuse_enabled:
            problems.append(
                "LICENSING_CROSS_ENTITY_REUSE_ENABLED must remain false in production; "
                "cross-entity reuse is granted per value with manager approval"
            )
        if self.licensing_enabled and self.auth_mode == "development":
            problems.append("production licensing cannot use development authentication")
        if self.tracker_import_enabled and self.evidence_storage_backend == "filesystem":
            problems.append(
                "production tracker imports require governed evidence storage for the "
                "original source file"
            )
        return problems

    def _portal_problems(self) -> list[str]:
        """Milestone 7's human-only and session-security boundary."""
        problems: list[str] = []
        human_controls = {
            "PORTAL_LOGIN_HUMAN_ONLY": self.portal_login_human_only,
            "PORTAL_MFA_HUMAN_ONLY": self.portal_mfa_human_only,
            "PORTAL_CAPTCHA_HUMAN_ONLY": self.portal_captcha_human_only,
            "PORTAL_TERMS_ACCEPTANCE_HUMAN_ONLY": self.portal_terms_acceptance_human_only,
            "PORTAL_ATTESTATION_HUMAN_ONLY": self.portal_attestation_human_only,
            "PORTAL_SIGNATURE_HUMAN_ONLY": self.portal_signature_human_only,
            "PORTAL_PAYMENT_HUMAN_ONLY": self.portal_payment_human_only,
            "PORTAL_FINAL_SUBMIT_HUMAN_ONLY": self.portal_final_submit_human_only,
        }
        for setting, enabled in human_controls.items():
            if not enabled:
                problems.append(f"{setting} must remain true in Milestone 7")
        if self.portal_captcha_solving_enabled:
            problems.append("PORTAL_CAPTCHA_SOLVING_ENABLED must remain false")
        if self.portal_mfa_bypass_enabled:
            problems.append("PORTAL_MFA_BYPASS_ENABLED must remain false")
        if self.browser_remote_debugging_url:
            problems.append("BROWSER_REMOTE_DEBUGGING_URL is not supported")
        if self.browser_session_state_persistence and not (
            self.browser_session_encryption_key_reference
        ):
            problems.append(
                "persistent browser state requires BROWSER_SESSION_ENCRYPTION_KEY_REFERENCE"
            )
        if self.portal_default_automation_level == "UNATTENDED_SUBMISSION":
            problems.append("UNATTENDED_SUBMISSION is not a supported automation level")
        if self.portal_upload_max_files <= 0 or self.portal_upload_max_total_bytes <= 0:
            problems.append("portal upload limits must be positive")
        if self.browser_worker_pool_size <= 0:
            problems.append("BROWSER_WORKER_POOL_SIZE must be positive")
        if self.browser_session_max_minutes <= 0 or self.browser_inactivity_timeout_minutes <= 0:
            problems.append("browser session timeouts must be positive")
        if self.app_env == "production":
            if self.portal_automation_enabled and not self.portal_allowed_hosts:
                problems.append("production portal automation requires PORTAL_ALLOWED_HOSTS")
            if not self.portal_require_active_review:
                problems.append("production requires PORTAL_REQUIRE_ACTIVE_REVIEW")
            if self.auth_mode == "development":
                problems.append(
                    "production portal assistance cannot use development authentication"
                )
            if self.browser_session_state_persistence:
                problems.append(
                    "production browser session persistence is disabled for Milestone 7"
                )
        return problems

    def _deployment_problems(self) -> list[str]:
        """Milestone 8 deployment sanity checks.

        A deployment must fail loudly rather than start with a half-configured
        environment: a production API with no allowed browser origin, a public
        URL served over plain HTTP, or a production service still pointing at a
        developer database are all deployment mistakes, not runtime conditions.
        """
        problems: list[str] = []
        deployed = self.app_env in ("staging", "production")

        for name, value in (("FRONTEND_URL", self.frontend_url), ("BACKEND_URL", self.backend_url)):
            if not value:
                continue
            if deployed and not value.startswith("https://"):
                problems.append(f"{name} must use HTTPS outside local/test")
            if deployed and _is_loopback(value):
                problems.append(f"{name} must not point at localhost outside local/test")

        if self.app_env != "production":
            return problems

        if not self.cors_origins:
            problems.append("production requires CORS_ORIGINS containing the portal origin")
        if self.frontend_url:
            origin = self.frontend_url.rstrip("/")
            if origin not in {value.rstrip("/") for value in self.cors_origins}:
                problems.append("production CORS_ORIGINS must contain FRONTEND_URL")
        if _is_loopback(self.database_url):
            problems.append("production DATABASE_URL must not point at a local database")
        return problems

    @property
    def graph_allowed_host(self) -> str:
        return self.graph_base_url.split("://", 1)[-1].split("/", 1)[0]

    @property
    def graph_change_types(self) -> list[str]:
        return [c.strip() for c in self.graph_subscription_change_types.split(",") if c.strip()]

    @property
    def graph_delta_select(self) -> list[str]:
        return [f.strip() for f in self.graph_delta_select_fields.split(",") if f.strip()]

    @property
    def notification_url(self) -> str:
        return self.public_base_url.rstrip("/") + self.graph_notification_path

    @property
    def lifecycle_url(self) -> str:
        return self.public_base_url.rstrip("/") + self.graph_lifecycle_path

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.database_url

    @property
    def sharepoint_drive_ids(self) -> dict[str, str | None]:
        return {
            "MASTER_DOCUMENTS": self.sharepoint_master_documents_drive_id,
            "WORKING_DOCUMENTS": self.sharepoint_working_documents_drive_id,
            "BONDS": self.sharepoint_bonds_drive_id,
            "SUBMITTED_FILINGS": self.sharepoint_submitted_filings_drive_id,
            "LICENSES_CERTIFICATES": self.sharepoint_licenses_drive_id,
            "REGULATOR_CORRESPONDENCE": self.sharepoint_correspondence_drive_id,
            "PAYMENTS_RECEIPTS": self.sharepoint_payments_drive_id,
            "OFFICIAL_FORMS_CHECKLISTS": self.sharepoint_forms_drive_id,
            "QUARANTINE": self.sharepoint_quarantine_drive_id,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

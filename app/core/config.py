"""Typed application configuration loaded from the environment."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "test", "staging", "production"]
AuthMode = Literal["development", "entra"]
LogFormat = Literal["json", "console"]
GraphCredentialMode = Literal["client_secret", "certificate"]
EvidenceBackend = Literal["filesystem", "sharepoint"]
SharePointPermissionMode = Literal["sites_selected", "tenant_wide"]
UploadConflictBehavior = Literal["fail", "rename", "replace-current-version"]


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

    cors_origins: list[str] = Field(default_factory=list, alias="CORS_ORIGINS")

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
    entra_allowed_algorithms: list[str] = Field(
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
    ai_allowed_data_classes: list[str] = Field(
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
    graph_expected_mailbox_address: str | None = Field(
        default=None, alias="GRAPH_EXPECTED_MAILBOX_ADDRESS"
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
    allowed_attachment_mime_types: list[str] = Field(
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
    document_allowed_mime_types: list[str] = Field(
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
    document_allowed_extensions: list[str] = Field(
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
    document_expiry_alert_days: list[int] = Field(
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

    @field_validator(
        "cors_origins",
        "allowed_attachment_mime_types",
        "document_allowed_mime_types",
        "document_allowed_extensions",
        "document_expiry_alert_days",
        mode="before",
    )
    @classmethod
    def _split_comma_lists(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

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
        if problems:
            raise ValueError("; ".join(problems))
        return self

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

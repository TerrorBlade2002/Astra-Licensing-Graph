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
EvidenceBackend = Literal["filesystem"]


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

    prototype_import_root: str = Field(default="./prototype-data", alias="PROTOTYPE_IMPORT_ROOT")

    # ------------------------------------------------------------ Graph core
    graph_enabled: bool = Field(default=False, alias="GRAPH_ENABLED")
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

    @field_validator("cors_origins", "allowed_attachment_mime_types", mode="before")
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
        if self.app_env == "production":
            if self.auth_mode == "development":
                problems.append("AUTH_MODE=development is not allowed in production")
            if self.sql_echo:
                problems.append("SQL_ECHO must be disabled in production")
            if "*" in self.cors_origins:
                problems.append("CORS_ORIGINS must not contain '*' in production")
            if self.evidence_storage_backend == "filesystem":
                problems.append("EVIDENCE_STORAGE_BACKEND=filesystem is not allowed in production")
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

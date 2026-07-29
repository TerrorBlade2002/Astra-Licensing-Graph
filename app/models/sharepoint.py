"""SharePoint repository-resource and synchronization models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SharePointSite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sharepoint_sites"

    graph_site_id: Mapped[str] = mapped_column(unique=True, nullable=False)
    hostname: Mapped[str | None]
    site_path: Mapped[str | None]
    display_name: Mapped[str | None]
    web_url: Mapped[str | None]
    permission_mode: Mapped[str] = mapped_column(nullable=False)
    expected_app_id: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    last_verified_at: Mapped[datetime | None]
    last_permission_check_at: Mapped[datetime | None]
    last_error_code: Mapped[str | None]
    last_error_message: Mapped[str | None]


class SharePointDrive(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sharepoint_drives"
    __table_args__ = (
        UniqueConstraint("site_id", "graph_drive_id", name="uq_sharepoint_drives_site_graph"),
        Index(
            "uq_sharepoint_drives_active_purpose",
            "site_id",
            "purpose",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sharepoint_sites.id", ondelete="RESTRICT"), nullable=False
    )
    graph_drive_id: Mapped[str] = mapped_column(nullable=False)
    graph_list_id: Mapped[str | None]
    root_drive_item_id: Mapped[str | None]
    display_name: Mapped[str] = mapped_column(nullable=False)
    drive_type: Mapped[str | None]
    web_url: Mapped[str | None]
    purpose: Mapped[str] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    last_verified_at: Mapped[datetime | None]


class SharePointFolder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sharepoint_folders"
    __table_args__ = (
        UniqueConstraint("drive_id", "graph_drive_item_id", name="uq_sharepoint_folders_item"),
        UniqueConstraint("drive_id", "logical_path", name="uq_sharepoint_folders_path"),
    )

    drive_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sharepoint_drives.id", ondelete="RESTRICT"), nullable=False
    )
    graph_drive_item_id: Mapped[str] = mapped_column(nullable=False)
    parent_graph_drive_item_id: Mapped[str | None]
    display_name: Mapped[str] = mapped_column(nullable=False)
    logical_path: Mapped[str] = mapped_column(nullable=False)
    purpose: Mapped[str | None]
    web_url: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    last_verified_at: Mapped[datetime | None]


class SharePointSyncState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sharepoint_sync_state"

    drive_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sharepoint_drives.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    delta_link: Mapped[str | None]
    needs_rebaseline: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    last_started_at: Mapped[datetime | None]
    last_completed_at: Mapped[datetime | None]
    last_delta_url_fingerprint: Mapped[str | None]
    last_page_count: Mapped[int | None] = mapped_column(Integer)
    last_change_count: Mapped[int | None] = mapped_column(Integer)
    lease_owner: Mapped[str | None]
    lease_expires_at: Mapped[datetime | None]
    last_error_code: Mapped[str | None]
    last_error_message: Mapped[str | None]


class SharePointUploadSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sharepoint_upload_sessions"

    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_jobs.id", ondelete="CASCADE"), nullable=False
    )
    encrypted_upload_url: Mapped[str | None]
    upload_url_fingerprint: Mapped[str] = mapped_column(nullable=False)
    next_expected_offset: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)

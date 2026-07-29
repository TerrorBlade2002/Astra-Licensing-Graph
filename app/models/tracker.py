"""Master-tracker import runs and per-row provenance.

Every imported row is preserved verbatim in ``source_data`` alongside a
``row_fingerprint``. That combination is what makes a spreadsheet migration
auditable and repeatable: re-importing the same file recognises unchanged rows,
and a disputed inventory value can always be traced back to the exact cell it
came from.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.imports.enums import ImportRowAction, ImportRunStatus
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, enum_check

_ROW_ACTION_VALUES = ", ".join(f"'{member.value}'" for member in ImportRowAction)


class TrackerImportRun(UUIDPrimaryKeyMixin, Base):
    """One planning or applying pass over an uploaded tracker file."""

    __tablename__ = "tracker_import_runs"
    __table_args__ = (
        Index("ix_tracker_import_runs_status", "status", "started_at"),
        Index("ix_tracker_import_runs_hash", "source_sha256"),
        enum_check("status", ImportRunStatus, "status"),
    )

    source_filename: Mapped[str] = mapped_column(nullable=False)
    source_sha256: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    #: Column mapping plus sheet selection, exactly as confirmed by an Admin.
    mapping_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    dry_run: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    report_storage_uri: Mapped[str | None]
    #: The original spreadsheet preserved in governed evidence storage.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    #: Set when this run applies a previously planned dry run.
    plan_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tracker_import_runs.id", ondelete="SET NULL")
    )
    sheet_name: Mapped[str | None]
    detected_headers: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    initiated_by_actor: Mapped[str | None]
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[datetime | None]
    last_error_message: Mapped[str | None]


class TrackerImportRow(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A single spreadsheet row, its normalization, and its outcome."""

    __tablename__ = "tracker_import_rows"
    __table_args__ = (
        UniqueConstraint("import_run_id", "row_number", name="uq_tracker_import_rows_number"),
        Index("ix_tracker_import_rows_run", "import_run_id", "action"),
        Index("ix_tracker_import_rows_fingerprint", "row_fingerprint"),
        Index("ix_tracker_import_rows_target", "target_record_id"),
        # action stays NULL while a run is still planning, so the shared
        # enum_check helper (which forbids NULL) cannot express this.
        CheckConstraint(
            f"action IS NULL OR action IN ({_ROW_ACTION_VALUES})",
            name="action",
        ),
    )

    import_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracker_import_runs.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Digest of the normalized business key, used to detect repeat imports.
    row_fingerprint: Mapped[str] = mapped_column(nullable=False)
    #: Verbatim cell values as text. Formulas are stored as their cached value or
    #: as the formula string treated purely as data; they are never evaluated.
    source_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    normalized_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    action: Mapped[str | None]
    target_record_id: Mapped[uuid.UUID | None]
    #: Machine-readable findings: {"code": ..., "field": ..., "detail": ...}.
    error_details: Mapped[list[Any] | None] = mapped_column(JSONB)

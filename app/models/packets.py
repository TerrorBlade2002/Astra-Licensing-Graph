"""Packet templates and immutable generated document packets.

An approved packet is a frozen snapshot: it pins ``document_version_id`` and the
SHA-256 of every included file, and records what was deliberately omitted and
what is still missing. Replacing a document produces a new packet **version**
rather than editing the approved one, so a manifest always describes exactly what
was assembled at approval time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.licensing.enums import CaseType
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_check
from app.packets.enums import PacketItemStatus, PacketStatus, PacketTemplateStatus

_CASE_TYPE_VALUES = ", ".join(f"'{member.value}'" for member in CaseType)


class PacketTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reusable checklist of document types required for a filing."""

    __tablename__ = "packet_templates"
    __table_args__ = (
        Index("ix_packet_templates_scope", "jurisdiction_id", "license_type_id", "case_type"),
        # case_type is nullable (a template may apply to any case type) so the
        # shared enum_check helper, which forbids NULL, cannot be used here.
        CheckConstraint(
            f"case_type IS NULL OR case_type IN ({_CASE_TYPE_VALUES})",
            name="case_type",
        ),
        enum_check("status", PacketTemplateStatus, "status"),
    )

    template_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jurisdictions.id", ondelete="RESTRICT")
    )
    license_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("license_types.id", ondelete="RESTRICT")
    )
    case_type: Mapped[str | None]
    status: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None]
    #: Snapshot of the checklist source (vendor or regulator) this came from.
    requirement_source_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("requirement_source_snapshots.id", ondelete="SET NULL")
    )


class PacketTemplateItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One checklist line: which document type, required or optional, how chosen."""

    __tablename__ = "packet_template_items"
    __table_args__ = (
        UniqueConstraint("packet_template_id", "item_key", name="uq_packet_template_items_key"),
        Index("ix_packet_template_items_template", "packet_template_id", "sort_order"),
    )

    packet_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("packet_templates.id", ondelete="CASCADE"), nullable=False
    )
    item_key: Mapped[str] = mapped_column(nullable=False)
    document_type: Mapped[str] = mapped_column(nullable=False)
    required: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    #: Declarative selection policy consumed by app.packets.matching: strategy,
    #: max age in days, whether reuse approval is mandatory, and so on.
    selection_policy: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    instructions: Mapped[str | None]


class DocumentPacket(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A generated, versioned packet for one compliance case."""

    __tablename__ = "document_packets"
    __table_args__ = (
        UniqueConstraint("compliance_case_id", "version", name="uq_document_packets_version"),
        Index("ix_document_packets_case", "compliance_case_id", "status"),
        CheckConstraint("version >= 1", name="version"),
        enum_check("status", PacketStatus, "status"),
    )

    packet_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    compliance_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_cases.id", ondelete="CASCADE"), nullable=False
    )
    packet_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("packet_templates.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    #: Digest over the ordered manifest. Any document change alters this, which
    #: is how a tampered or stale packet is detected.
    manifest_sha256: Mapped[str | None]
    manifest: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    archive_storage_uri: Mapped[str | None]
    archive_sha256: Mapped[str | None]
    archive_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    cover_sheet_storage_uri: Mapped[str | None]
    missing_items: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    validation_results: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_by_actor: Mapped[str | None]
    reviewed_by_actor: Mapped[str | None]
    approved_at: Mapped[datetime | None]
    built_at: Mapped[datetime | None]
    superseded_by_packet_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_packets.id", ondelete="SET NULL")
    )
    rejection_reason: Mapped[str | None]


class DocumentPacketItem(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One resolved (or unresolved) checklist line inside a packet."""

    __tablename__ = "document_packet_items"
    __table_args__ = (
        UniqueConstraint(
            "document_packet_id", "packet_item_key", name="uq_document_packet_items_key"
        ),
        Index("ix_document_packet_items_packet", "document_packet_id", "sort_order"),
        Index("ix_document_packet_items_document", "document_id"),
        enum_check("status", PacketItemStatus, "status"),
    )

    document_packet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_packets.id", ondelete="CASCADE"), nullable=False
    )
    packet_item_key: Mapped[str] = mapped_column(nullable=False)
    document_type: Mapped[str | None]
    #: RESTRICT: a document cited by an approved packet manifest must not vanish.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT")
    )
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(nullable=False)
    inclusion_reason: Mapped[str | None]
    #: Recorded so a later hash mismatch proves the file changed after assembly.
    document_sha256: Mapped[str | None]
    filename_in_archive: Mapped[str | None]
    required: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    #: Set when a reviewer deliberately included or excluded an item by hand.
    override_by_actor: Mapped[str | None]
    override_reason: Mapped[str | None]
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))

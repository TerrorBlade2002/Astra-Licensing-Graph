"""Versioned email classifications."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import EmailType
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, enum_check

if TYPE_CHECKING:
    from app.models.email import Email
    from app.models.review import ClassificationReview


class Classification(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "classifications"
    __table_args__ = (
        UniqueConstraint("email_id", "version", name="uq_classifications_email_version"),
        Index(
            "uq_classifications_current",
            "email_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        enum_check("email_type", EmailType, "email_type"),
    )

    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(nullable=False)
    vendor: Mapped[str | None]
    email_type: Mapped[str] = mapped_column(nullable=False)
    states: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{}'")
    )
    license_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{}'")
    )
    license_numbers: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{}'")
    )
    requested_information: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    documents: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    action_required: Mapped[bool] = mapped_column(nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    summary: Mapped[str | None]
    proposed_action: Mapped[str | None]
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(nullable=False)
    classification_method: Mapped[str] = mapped_column(nullable=False)
    rule_matches: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    model_provider: Mapped[str | None]
    model_name: Mapped[str | None]
    model_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_current: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    email: Mapped[Email] = relationship(back_populates="classifications")
    reviews: Mapped[list[ClassificationReview]] = relationship(back_populates="classification")

"""Human review decisions on classifications."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import ReviewDecision
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, enum_check

if TYPE_CHECKING:
    from app.models.classification import Classification


class ClassificationReview(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "classification_reviews"
    __table_args__ = (
        Index("ix_classification_reviews_classification", "classification_id"),
        enum_check("decision", ReviewDecision, "decision"),
    )

    classification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classifications.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(nullable=False)
    reviewer_principal: Mapped[str] = mapped_column(nullable=False)
    review_notes: Mapped[str | None]
    corrected_classification: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(nullable=False)

    classification: Mapped[Classification] = relationship(back_populates="reviews")

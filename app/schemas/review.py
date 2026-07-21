"""Review API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.common import ORMModel


class ClassificationReviewOut(ORMModel):
    id: uuid.UUID
    classification_id: uuid.UUID
    decision: str
    reviewer_principal: str
    review_notes: str | None
    reviewed_at: datetime
    created_at: datetime

"""Declarative base with project-wide type mapping and naming conventions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import MetaData, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import DateTime

from app.db.naming import NAMING_CONVENTION


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy consumes this class attribute
        uuid.UUID: PGUUID(as_uuid=True),
        datetime: DateTime(timezone=True),
        str: Text(),
        dict[str, Any]: JSONB(),
    }

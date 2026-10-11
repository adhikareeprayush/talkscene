"""Declarative base and shared column types."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, MetaData, TypeDecorator, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSONB on Postgres, JSON on SQLite - same Python type either way.
Json = JSON().with_variant(JSONB, "postgresql")


class UtcDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend.

    SQLite has no datetime type, so `DateTime(timezone=True)` round-trips
    through a string and comes back *naive* — and comparing that to
    `datetime.now(UTC)` raises. Postgres does the right thing already. Rather
    than sprinkle defensive `.replace(tzinfo=...)` calls at every comparison,
    normalise once here: values go in as UTC and always come back aware.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value.astimezone(dt.UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now(), default=utcnow, nullable=False
    )

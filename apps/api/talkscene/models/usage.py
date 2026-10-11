from __future__ import annotations

import datetime as dt

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.ids import ledger_id
from .base import Base, TimestampMixin, UtcDateTime


class UsageLedger(Base):
    """Every billable provider call. Powers quota meters and cost dashboards."""

    __tablename__ = "usage_ledger"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ledger_id)
    user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    capability: Mapped[str] = mapped_column(String(16), nullable=False)  # llm|stt|tts|pron
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)  # requests|tokens|chars|seconds
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    ok: Mapped[bool] = mapped_column(default=True, nullable=False)
    ts: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, default=lambda: dt.datetime.now(dt.UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_usage_user_ts", "user_id", "ts"),
        Index("ix_usage_provider_ts", "provider", "ts"),
    )


class TtsCache(Base, TimestampMixin):
    """Scripted lines repeat constantly; the plan expects a 30-50% hit rate (§4)."""

    __tablename__ = "tts_cache"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    voice: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    chars: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), default="audio/mpeg", nullable=False)
    hits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

from __future__ import annotations

import datetime as dt

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.ids import card_id, vocab_id
from .base import Base, TimestampMixin, UtcDateTime


class VocabItem(Base, TimestampMixin):
    __tablename__ = "vocab_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=vocab_id)
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    term: Mapped[str] = mapped_column(String(120), nullable=False)
    reading: Mapped[str | None] = mapped_column(String(160))
    meaning: Mapped[str] = mapped_column(Text, nullable=False)
    # The sentence the learner actually met it in - what makes the card stick.
    example: Mapped[str | None] = mapped_column(Text)
    source_session_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("sessions.id", ondelete="SET NULL")
    )

    card: Mapped[SrsCard | None] = relationship(
        back_populates="item", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (Index("ix_vocab_user_lang_term", "user_id", "language", "term", unique=True),)


class SrsCard(Base):
    """FSRS scheduling state (see learning/fsrs.py)."""

    __tablename__ = "srs_cards"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=card_id)
    vocab_item_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("vocab_items.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    due_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, index=True, nullable=False)
    last_reviewed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    stability: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    difficulty: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    state: Mapped[str] = mapped_column(String(12), default="new", nullable=False)
    scheduled_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    item: Mapped[VocabItem] = relationship(back_populates="card")

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.ids import attempt_id, drill_id
from .base import Base, Json, TimestampMixin


class Drill(Base, TimestampMixin):
    """One shadowing sentence. Attempts hold the scores (ADR 0003, track 2)."""

    __tablename__ = "drills"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=drill_id)
    session_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("sessions.id", ondelete="SET NULL")
    )
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    ref_text: Mapped[str] = mapped_column(Text, nullable=False)
    translation_en: Mapped[str | None] = mapped_column(Text)
    focus_words: Mapped[list | None] = mapped_column(Json)
    reference_audio_key: Mapped[str | None] = mapped_column(String(200))
    best_accuracy: Mapped[float | None] = mapped_column(Float)

    attempts: Mapped[list[DrillAttempt]] = relationship(
        back_populates="drill",
        cascade="all, delete-orphan",
        order_by="DrillAttempt.attempt",
        lazy="selectin",
    )


class DrillAttempt(Base, TimestampMixin):
    __tablename__ = "drill_attempts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=attempt_id)
    drill_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("drills.id", ondelete="CASCADE"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    audio_key: Mapped[str | None] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="azure")
    accuracy: Mapped[float | None] = mapped_column(Float)
    fluency: Mapped[float | None] = mapped_column(Float)
    completeness: Mapped[float | None] = mapped_column(Float)
    prosody: Mapped[float | None] = mapped_column(Float)
    recognized_text: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(Json)  # per-word / per-phoneme detail

    drill: Mapped[Drill] = relationship(back_populates="attempts")

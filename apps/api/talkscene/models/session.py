from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.ids import session_id, turn_id
from .base import Base, Json, TimestampMixin, UtcDateTime

if TYPE_CHECKING:
    from .scenario import Scenario

# created -> active -> analyzing -> completed, or abandoned from anywhere.
SessionStatus = ("created", "active", "analyzing", "completed", "abandoned")


class PracticeSession(Base):
    """One roleplay. Named PracticeSession so it never reads as a DB session."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=session_id)
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    scenario_id: Mapped[str] = mapped_column(String(80), ForeignKey("scenarios.id"), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    level: Mapped[str] = mapped_column(String(4), nullable=False)
    target_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    status: Mapped[str] = mapped_column(String(16), default="created", nullable=False, index=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, default=lambda: dt.datetime.now(dt.UTC), nullable=False
    )
    ended_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    # [{id, text, done, turn_completed}] - re-injected into the prompt each turn.
    goals_state: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    # Which provider served each capability, and every failover that happened.
    provider_trace: Mapped[dict] = mapped_column(Json, default=dict, nullable=False)
    options: Mapped[dict] = mapped_column(Json, default=dict, nullable=False)
    # Rolling 3-line summary of everything older than the prompt window (§6.4).
    summary: Mapped[str | None] = mapped_column(Text)

    # Eager by default: every read path needs the transcript, and a lazy load
    # from async code raises MissingGreenlet rather than degrading.
    turns: Mapped[list[Turn]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Turn.idx",
        lazy="selectin",
    )
    scenario: Mapped[Scenario] = relationship(lazy="selectin")

    @property
    def user_turns_used(self) -> int:
        return sum(1 for t in self.turns if t.role == "user")


class Turn(Base, TimestampMixin):
    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=turn_id)
    session_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(8), nullable=False)  # ai | user
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    translation_en: Mapped[str | None] = mapped_column(Text)
    romanization: Mapped[str | None] = mapped_column(Text)
    audio_key: Mapped[str | None] = mapped_column(String(200))
    # An AI turn is synthesized sentence by sentence for streaming, so it has
    # one storage key per sentence; `audio_key` is the first of them.
    audio_keys: Mapped[list | None] = mapped_column(Json)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    stt_provider: Mapped[str | None] = mapped_column(String(32))
    stt_words: Mapped[list | None] = mapped_column(Json)  # [{w, start, end, prob}]
    no_speech_prob: Mapped[float | None] = mapped_column()
    llm_provider: Mapped[str | None] = mapped_column(String(32))
    tts_provider: Mapped[str | None] = mapped_column(String(32))
    suggested_replies: Mapped[list | None] = mapped_column(Json)
    latency_ms: Mapped[dict | None] = mapped_column(Json)  # {stt, llm_first_token, llm, tts_first}
    # Seconds from the AI's audio finishing to the learner starting to speak.
    response_delay_ms: Mapped[int | None] = mapped_column(Integer)

    session: Mapped[PracticeSession] = relationship(back_populates="turns")

    __table_args__ = (Index("ix_turns_session_idx", "session_id", "idx", unique=True),)

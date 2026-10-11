from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.ids import user_id
from .base import Base, Json, TimestampMixin, UtcDateTime


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=user_id)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    display_name: Mapped[str | None] = mapped_column(String(80))
    native_lang: Mapped[str] = mapped_column(String(8), default="en")
    ui_lang: Mapped[str] = mapped_column(String(8), default="en")
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    plan: Mapped[str] = mapped_column(String(16), default="free", nullable=False)  # free|plus|byok
    # Learning profile, set during onboarding.
    target_lang: Mapped[str | None] = mapped_column(String(8))
    level: Mapped[str | None] = mapped_column(String(4))
    goals: Mapped[list | None] = mapped_column(Json)  # ["travel", "work", ...]
    daily_goal_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    streak_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_active_on: Mapped[dt.date | None] = mapped_column()
    deleted_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)

    prefs: Mapped[UserPref | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )


class UserPref(Base):
    __tablename__ = "user_prefs"

    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tts_provider: Mapped[str] = mapped_column(String(16), default="standard")  # standard|premium
    tts_rate: Mapped[float] = mapped_column(Float, default=1.0)
    show_romanization: Mapped[bool] = mapped_column(Boolean, default=True)
    show_furigana: Mapped[bool] = mapped_column(Boolean, default=True)
    show_translation: Mapped[bool] = mapped_column(Boolean, default=True)
    mic_mode: Mapped[str] = mapped_column(String(16), default="push")  # push|handsfree|text
    correction_style: Mapped[str] = mapped_column(String(16), default="end_only")
    keep_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    theme: Mapped[str] = mapped_column(String(8), default="system")
    byok_keys_encrypted: Mapped[dict | None] = mapped_column(Json)

    user: Mapped[User] = relationship(back_populates="prefs")

    @staticmethod
    def defaults(uid: str) -> UserPref:
        return UserPref(user_id=uid)

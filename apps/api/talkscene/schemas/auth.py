from __future__ import annotations

from typing import Literal

from pydantic import EmailStr, Field

from .common import Lang, Level, Schema


class GuestRequest(Schema):
    turnstile_token: str | None = Field(
        None, description="Cloudflare Turnstile token; required in production."
    )
    native_lang: Lang = "en"


class SignupRequest(Schema):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str | None = Field(None, max_length=80)
    native_lang: Lang = "en"
    # Lets a guest keep the sessions they already recorded.
    link_guest_token: str | None = None


class LoginRequest(Schema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(Schema):
    refresh_token: str


class TokenPair(Schema):
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    user_id: str
    is_guest: bool


class Prefs(Schema):
    tts_provider: Literal["standard", "premium"] = "standard"
    tts_rate: float = Field(1.0, ge=0.5, le=1.5)
    show_romanization: bool = True
    show_furigana: bool = True
    show_translation: bool = True
    mic_mode: Literal["push", "handsfree", "text"] = "push"
    correction_style: Literal["end_only", "gentle_recast"] = "end_only"
    keep_audio: bool = False
    theme: Literal["system", "light", "dark"] = "system"


class PrefsUpdate(Schema):
    tts_provider: Literal["standard", "premium"] | None = None
    tts_rate: float | None = Field(None, ge=0.5, le=1.5)
    show_romanization: bool | None = None
    show_furigana: bool | None = None
    show_translation: bool | None = None
    mic_mode: Literal["push", "handsfree", "text"] | None = None
    correction_style: Literal["end_only", "gentle_recast"] | None = None
    keep_audio: bool | None = None
    theme: Literal["system", "light", "dark"] | None = None


class ByokKeys(Schema):
    """Learner-supplied provider keys. Stored encrypted, never returned."""

    groq: str | None = None
    xai: str | None = None
    gemini: str | None = None
    deepgram: str | None = None
    azure_speech_key: str | None = None
    azure_speech_region: str | None = None


class Me(Schema):
    id: str
    email: str | None
    display_name: str | None
    is_guest: bool
    plan: str
    native_lang: str
    ui_lang: str
    target_lang: Lang | None
    level: Level | None
    goals: list[str]
    daily_goal_minutes: int
    streak_days: int
    prefs: Prefs
    byok_configured: list[str] = Field(
        default_factory=list, description="Which BYOK providers have a key stored."
    )


class MeUpdate(Schema):
    display_name: str | None = Field(None, max_length=80)
    native_lang: Lang | None = None
    ui_lang: Lang | None = None
    target_lang: Lang | None = None
    level: Level | None = None
    goals: list[str] | None = None
    daily_goal_minutes: int | None = Field(None, ge=5, le=120)
    prefs: PrefsUpdate | None = None
    byok: ByokKeys | None = None

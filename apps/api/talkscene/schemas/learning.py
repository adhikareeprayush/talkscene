from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from .common import Lang, Schema


# ── drills (§11.3 G) ────────────────────────────────────────────────────────
class PhonemeScore(Schema):
    phoneme: str
    score: float


class WordScore(Schema):
    word: str
    accuracy: float
    error_type: str = "None"
    phonemes: list[PhonemeScore] = Field(default_factory=list)


class DrillAttempt(Schema):
    id: str
    attempt: int
    provider: str
    accuracy: float | None = None
    fluency: float | None = None
    completeness: float | None = None
    prosody: float | None = None
    recognized_text: str | None = None
    words: list[WordScore] = Field(default_factory=list)
    authoritative: bool = Field(
        description=(
            "False when scored by the heuristic fallback: no phoneme data, and the numbers "
            "are estimates (ADR 0003)."
        )
    )
    audio_url: str | None = None
    created_at: dt.datetime | None = None


class Drill(Schema):
    id: str
    language: Lang
    ref_text: str
    translation_en: str | None = None
    focus_words: list[str] = Field(default_factory=list)
    reference_audio_url: str | None = None
    best_accuracy: float | None = None
    attempts: list[DrillAttempt] = Field(default_factory=list)


class CreateDrillsRequest(Schema):
    session_id: str | None = Field(None, description="Build the set from this session's report.")
    sentences: list[str] | None = Field(
        None, max_length=6, description="Or supply your own reference sentences."
    )
    language: Lang | None = None


class DrillSet(Schema):
    drills: list[Drill]
    quota: DrillQuota


class DrillQuota(Schema):
    seconds_used_this_month: int
    seconds_limit: int
    authoritative_scoring_available: bool
    note: str = ""


# ── vocabulary + SRS (§11.3 I) ──────────────────────────────────────────────
class VocabIn(Schema):
    language: Lang
    term: str = Field(min_length=1, max_length=120)
    reading: str | None = Field(None, max_length=160)
    meaning: str = Field(min_length=1, max_length=600)
    example: str | None = Field(None, max_length=600)
    source_session_id: str | None = None


class VocabOut(Schema):
    id: str
    language: Lang
    term: str
    reading: str | None
    meaning: str
    example: str | None
    source_session_id: str | None
    created_at: dt.datetime
    due_at: dt.datetime | None = None
    state: str | None = None
    reps: int = 0
    lapses: int = 0


class SrsCard(Schema):
    card_id: str
    vocab: VocabOut
    due_at: dt.datetime
    state: str
    reps: int
    lapses: int
    stability: float
    difficulty: float
    # What each button would schedule, e.g. {"again": "1m", "good": "4d"}.
    intervals: dict[str, str] = Field(default_factory=dict)


class ReviewRequest(Schema):
    rating: Literal[1, 2, 3, 4] = Field(description="1 Again, 2 Hard, 3 Good, 4 Easy")


class ReviewResponse(Schema):
    card_id: str
    due_at: dt.datetime
    scheduled_days: int
    state: str
    remaining_due: int


# ── progress (§11.3 H) ──────────────────────────────────────────────────────
class SkillRadar(Schema):
    task_completion: float
    grammar: float
    fluency: float
    pronunciation: float
    vocabulary: float


class DayActivity(Schema):
    date: dt.date
    minutes: float
    sessions: int


class LanguageProgress(Schema):
    language: Lang
    sessions: int
    minutes: float
    avg_score: float | None
    latest_cefr: str | None
    words_learned: int


class Progress(Schema):
    streak_days: int
    daily_goal_minutes: int
    minutes_today: float
    sessions_total: int
    minutes_total: float
    words_learned: int
    cards_due: int
    skill_radar: SkillRadar | None = None
    score_trend: list[int] = Field(default_factory=list)
    activity: list[DayActivity] = Field(default_factory=list)
    by_language: list[LanguageProgress] = Field(default_factory=list)


# ── usage / quotas (§11.3 J) ────────────────────────────────────────────────
class QuotaMeter(Schema):
    key: str
    label: str
    used: float
    limit: float | None
    unit: str
    resets: str
    exhausted: bool = False


class Usage(Schema):
    plan: str
    meters: list[QuotaMeter]
    byok_active: bool = False


class ProviderHealth(Schema):
    capability: Literal["llm", "stt", "tts", "pron"]
    provider: str
    configured: bool
    state: Literal["ok", "cooling", "unconfigured"]
    cooling_until: float | None = None


class SystemStatus(Schema):
    status: Literal["ok", "degraded"]
    mode: Literal["auto", "mock", "live"]
    live_providers: dict[str, list[str]] = Field(default_factory=dict)
    degraded: list[str] = Field(default_factory=list)
    message: str = ""


DrillSet.model_rebuild()

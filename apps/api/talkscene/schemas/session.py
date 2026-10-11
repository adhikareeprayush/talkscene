from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from .catalog import GoalState
from .common import Lang, Level, Schema

SessionStatus = Literal["created", "active", "analyzing", "completed", "abandoned"]


class SessionOptions(Schema):
    show_translation: bool = True
    romanization: bool = True
    furigana: bool = True
    input: Literal["voice", "text"] = "voice"
    hints: bool = True
    tts_tier: Literal["standard", "premium"] = "standard"
    tts_rate: float = Field(1.0, ge=0.5, le=1.5)
    keep_audio: bool = False


class StartSessionRequest(Schema):
    scenario_id: str
    target_turns: int | None = Field(
        None, description="Defaults to the scenario's `turn_limits.default`."
    )
    options: SessionOptions = Field(default_factory=SessionOptions)


class WordTiming(Schema):
    w: str
    start: float
    end: float
    prob: float = 1.0


class TurnOut(Schema):
    idx: int
    role: Literal["ai", "user"]
    text: str
    translation_en: str | None = None
    romanization: str | None = None
    audio_url: str | None = None
    audio_sentences: int = 0
    suggested_replies: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    words: list[WordTiming] = Field(default_factory=list)
    stt_provider: str | None = None
    llm_provider: str | None = None
    tts_provider: str | None = None
    created_at: dt.datetime | None = None


class TurnBudget(Schema):
    target: int
    used: int


class SessionState(Schema):
    session_id: str
    scenario_id: str
    language: Lang
    level: Level
    status: SessionStatus
    turn_budget: TurnBudget
    goals: list[GoalState]
    options: SessionOptions
    started_at: dt.datetime
    ended_at: dt.datetime | None = None
    provider_trace: dict[str, list[str]] = Field(default_factory=dict)
    report_ready: bool = False


class StartSessionResponse(SessionState):
    ai_turn: TurnOut


class SessionDetail(SessionState):
    turns: list[TurnOut]


class SessionSummary(Schema):
    """One row in the history list (§11.3 H)."""

    session_id: str
    scenario_id: str
    scenario_title: str
    language: Lang
    level: Level
    status: SessionStatus
    icon: str | None = None
    started_at: dt.datetime
    ended_at: dt.datetime | None
    turns_used: int
    target_turns: int
    goals_done: int
    goals_total: int
    overall: int | None = None


class SubmitTurnRequest(Schema):
    """JSON body for a text turn. Voice turns use `multipart/form-data` instead."""

    text: str = Field(min_length=1, max_length=1200)
    # A number rather than an integer: clients compute this from
    # performance.now(), which is fractional, and rejecting a learner's turn
    # over a decimal in an optional timing field would be absurd. Rounded on use.
    response_delay_ms: float | None = Field(
        None,
        ge=0,
        description=(
            "Milliseconds from the AI finishing to the learner replying. Fractions are rounded."
        ),
    )


HintType = Literal["suggest", "translate", "explain", "slow"]


class HintRequest(Schema):
    type: HintType
    target: str | None = Field(
        None, description="Word or phrase for `explain`; turn text for `translate`."
    )
    turn_idx: int | None = None


class Explanation(Schema):
    term: str
    reading: str | None = None
    meaning: str
    part_of_speech: str | None = None
    example: str | None = None
    example_translation: str | None = None
    note: str | None = None


class HintResponse(Schema):
    type: HintType
    # `suggest` and `translate` are free: they reuse the metadata already
    # attached to the turn, so no extra LLM call is made (plan §6.5).
    billed: bool = False
    suggestions: list[str] = Field(default_factory=list)
    translation: str | None = None
    romanization: str | None = None
    explanation: Explanation | None = None
    audio_url: str | None = None
    hints_used: int = 0
    hints_limit: int = 0


class EndSessionResponse(Schema):
    session_id: str
    status: SessionStatus
    report_url: str
    eta_s: int = 8


class TtsRequest(Schema):
    text: str = Field(min_length=1, max_length=600)
    lang: Lang
    voice: str | None = None
    rate: float = Field(1.0, ge=0.5, le=1.5)


class SttResponse(Schema):
    text: str
    language: str
    provider: str
    duration_s: float
    no_speech_prob: float
    words: list[WordTiming] = Field(default_factory=list)

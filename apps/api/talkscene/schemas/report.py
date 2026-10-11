from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .catalog import GoalState
from .common import Lang, Level, Schema


class ScoreBreakdown(Schema):
    task_completion: float
    grammar: float
    fluency: float
    pronunciation: float | None = Field(
        None,
        description="null when the session had no audio, so there is nothing to estimate from.",
    )
    vocabulary: float
    weights: dict[str, float]
    pronunciation_basis: Literal["stt_confidence", "azure_pa", "unavailable"]
    excluded_from_overall: list[str] = Field(
        default_factory=list,
        description="Sub-scores with no evidence this session; the overall score renormalises.",
    )


class Pause(Schema):
    after_word: str
    seconds: float
    turn_idx: int


class UnclearWord(Schema):
    word: str
    turn_idx: int
    probability: float = Field(
        description="Speech-recognition confidence, not a pronunciation score (ADR 0003)."
    )


class Speaking(Schema):
    speaking_seconds: float
    word_count: int
    char_count: int
    words_per_minute: float
    chars_per_minute: float = Field(
        description="The meaningful rate for Korean and Japanese, which are not word-spaced."
    )
    rate_label: Literal["hesitant", "steady", "fast", "unknown"]
    avg_response_delay_ms: int | None = None
    max_response_delay_ms: int | None = None
    long_pauses: list[Pause] = Field(default_factory=list)
    longest_pause_s: float = 0.0
    filler_counts: dict[str, int] = Field(default_factory=dict)
    filler_total: int = 0
    words_per_turn: list[int] = Field(default_factory=list)
    turn_length_trend: Literal["growing", "flat", "shrinking"]
    native_language_turns: int = 0
    turns_measured: int = 0
    estimated_from_text: bool = False
    unclear_words: list[UnclearWord] = Field(default_factory=list)


class Correction(Schema):
    turn: int | None = None
    said: str
    better: str
    why: str
    category: str


class Goals(Schema):
    done: int
    total: int
    items: list[GoalState]


class Grammar(Schema):
    corrections: list[Correction] = Field(default_factory=list)
    note: str | None = None


class TargetHitRate(Schema):
    used: list[str] = Field(default_factory=list)
    missed: list[str] = Field(default_factory=list)
    rate: float | None = None


class Flashcard(Schema):
    id: str
    term: str
    meaning: str


class Vocabulary(Schema):
    used_well: list[str] = Field(default_factory=list)
    new: list[str] = Field(default_factory=list)
    suggested: list[dict[str, Any]] = Field(default_factory=list)
    target_hit_rate: TargetHitRate
    flashcards_created: list[Flashcard] = Field(default_factory=list)
    requires_account: bool = Field(
        False, description="True for guests: suggested words were not saved as flashcards."
    )


class DrillStub(Schema):
    id: str
    ref_text: str
    translation_en: str | None = None
    focus_words: list[str] = Field(default_factory=list)


class Pronunciation(Schema):
    confidence: Literal["estimated", "measured"] = Field(
        description=(
            "`estimated` means these come from speech-recognition confidence, not phoneme "
            "scoring. The UI must label them as estimates (ADR 0003)."
        )
    )
    basis: str
    unclear_words: list[UnclearWord] = Field(default_factory=list)
    focus_areas: str = ""
    disclaimer: str = ""
    drills: list[DrillStub] = Field(default_factory=list)


class RegisterCheck(Schema):
    language: str
    expected: Literal["casual", "polite", "formal"]
    detected: dict[str, int] = Field(default_factory=dict)
    dominant: str
    consistent: bool
    confidence: Literal["low", "medium", "high"]
    notes: str
    offending_turns: list[int] = Field(default_factory=list)


class NextSteps(Schema):
    focus: str | None = None
    next_scenario_id: str | None = None
    retry_scenario_id: str | None = None


class TranscriptLine(Schema):
    idx: int
    role: Literal["ai", "user"]
    text: str
    translation_en: str | None = None


class Report(Schema):
    session_id: str
    scenario_id: str
    language: Lang
    level: Level
    overall: int = Field(ge=0, le=100)
    estimated_cefr: str
    summary: str
    scores: ScoreBreakdown
    goals: Goals
    speaking: Speaking
    grammar: Grammar
    vocabulary: Vocabulary
    pronunciation: Pronunciation
    # `register` collides with a BaseModel attribute, so the field is named
    # `register_check` and serialised under its documented key.
    register_check: RegisterCheck = Field(alias="register")
    native_language_turns: int = 0
    next_steps: NextSteps
    transcript: list[TranscriptLine] = Field(default_factory=list)
    providers: dict[str, Any] = Field(default_factory=dict)


class ReportPending(Schema):
    status: Literal["analyzing"] = "analyzing"
    session_id: str
    eta_s: int = 8

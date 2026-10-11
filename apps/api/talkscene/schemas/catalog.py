from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import Category, Lang, Level, Schema


class VoiceInfo(Schema):
    azure: str | None = None
    deepgram: str | None = None
    browser_hint: str | None = None


class LanguageInfo(Schema):
    code: Lang
    name: str
    native_name: str
    flag: str
    accent: str = Field(description="Per-language accent colour token used by the UI.")
    romanization: bool
    furigana: bool
    pronunciation_assessment: bool
    premium_tts: bool
    note: str = ""
    scenario_count: int = 0
    levels: list[Level] = Field(default_factory=list)


class Goal(Schema):
    id: str
    text: str


class GoalState(Goal):
    done: bool = False
    turn_completed: int | None = None


class Persona(Schema):
    name: str
    role: str
    style: str


class Phrase(Schema):
    text: str
    reading: str | None = None
    meaning: str


class TurnLimits(Schema):
    min: int
    default: int
    max: int


class ScenarioCard(Schema):
    id: str
    language: Lang
    level: Level
    category: Category
    icon: str | None = None
    title: dict[str, str]
    summary: str
    estimated_minutes: int
    tags: list[str] = Field(default_factory=list)
    completed: bool = False
    best_score: int | None = None


class ScenarioBrief(ScenarioCard):
    version: int
    persona: Persona
    setting: str
    user_role: str
    goals: list[Goal]
    target_vocab: list[str]
    target_grammar: list[str]
    useful_phrases: list[Phrase] = Field(default_factory=list)
    cultural_notes: list[str] = Field(default_factory=list)
    turn_limits: TurnLimits
    voice: VoiceInfo = Field(default_factory=VoiceInfo)
    learner_register: Literal["casual", "polite", "formal"] | None = Field(
        None, description="The politeness level the learner should use; null for English."
    )


class CustomScenarioRequest(Schema):
    prompt: str = Field(
        min_length=8,
        max_length=600,
        description='Free text, e.g. "complaining to my landlord about a broken heater".',
    )
    language: Lang
    level: Level = "A2"
    publish: bool = Field(False, description="Admin only; learner scenarios stay private.")


class CustomScenarioResponse(Schema):
    scenario: ScenarioBrief
    moderation: str = "passed"

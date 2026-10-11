"""Fluency metrics computed from word timings — arithmetic, not an LLM call.

Plan §8.2 wants words per minute, response delay, pause distribution and filler
counts.  Every one of those is derivable from the per-word `start`/`end` that
Whisper and Nova-3 return, so asking a model for them would only invite
hallucinated numbers.  The LLM is told these values and told not to contradict
them (`prompts.feedback_user_prompt`).

Two language-specific details:

* Korean and Japanese are not word-spaced, so words-per-minute is a poor
  measure.  Characters per minute is reported alongside it, and the UI shows
  the appropriate one per language.
* "Unclear word" candidates come from STT confidence and are *labelled
  estimated* — they are never scored (ADR 0003).
"""

from __future__ import annotations

import itertools
import re
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

from ..providers.base import Word
from .prompts import FILLERS

LONG_PAUSE_S = 1.5
UNCLEAR_PROB = 0.6
CJK = ("ko", "ja")

# Comfortable spoken rates for an intermediate learner, used only to describe
# the measured rate in words ("steady", "hesitant") rather than to score it.
COMFORTABLE_WPM = {"ko": 90, "ja": 100, "de": 110, "en": 120}
COMFORTABLE_CPM = {"ko": 320, "ja": 340, "de": 700, "en": 720}

_WORD_CHARS = re.compile(r"[^\w぀-ヿ一-鿿가-힯]+", re.UNICODE)
_LATIN = re.compile(r"[A-Za-z]{3,}")


@dataclass(slots=True)
class Pause:
    after_word: str
    seconds: float
    turn_idx: int


@dataclass(slots=True)
class UnclearWord:
    word: str
    turn_idx: int
    probability: float


@dataclass(slots=True)
class FluencyReport:
    speaking_seconds: float = 0.0
    word_count: int = 0
    char_count: int = 0
    words_per_minute: float = 0.0
    chars_per_minute: float = 0.0
    rate_label: str = "unknown"  # hesitant | steady | fast
    avg_response_delay_ms: int | None = None
    max_response_delay_ms: int | None = None
    long_pauses: list[Pause] = field(default_factory=list)
    longest_pause_s: float = 0.0
    filler_counts: dict[str, int] = field(default_factory=dict)
    filler_total: int = 0
    words_per_turn: list[int] = field(default_factory=list)
    turn_length_trend: str = "flat"  # growing | flat | shrinking
    unclear_words: list[UnclearWord] = field(default_factory=list)
    native_language_turns: int = 0
    turns_measured: int = 0
    # True when no turn carried word timings, so the numbers above are text-only.
    estimated_from_text: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def tokenize_words(text: str, lang: str) -> list[str]:
    cleaned = _WORD_CHARS.sub(" ", text or "").strip()
    if not cleaned:
        return []
    return cleaned.split()


def count_chars(text: str) -> int:
    return len(_WORD_CHARS.sub("", text or ""))


def count_fillers(text: str, lang: str) -> dict[str, int]:
    out: dict[str, int] = {}
    haystack = (text or "").lower()
    for filler in FILLERS.get(lang, ()):
        needle = filler.lower()
        # Latin fillers need word boundaries ("um" must not match "umbrella");
        # Korean/Japanese fillers are not word-delimited, so count substrings.
        if needle.isascii():
            hits = len(re.findall(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", haystack))
        else:
            hits = haystack.count(needle)
        if hits:
            out[filler] = hits
    return out


def uses_native_language(text: str, lang: str) -> bool:
    """Flag a learner answering in English (or another Latin script) instead."""
    if lang == "en":
        return False
    return bool(_LATIN.search(text or ""))


def _trend(values: list[int]) -> str:
    if len(values) < 4:
        return "flat"
    half = len(values) // 2
    first = statistics.fmean(values[:half])
    second = statistics.fmean(values[half:])
    if second > first * 1.25:
        return "growing"
    if second < first * 0.8:
        return "shrinking"
    return "flat"


def _rate_label(wpm: float, cpm: float, lang: str) -> str:
    target = COMFORTABLE_CPM[lang] if lang in CJK else COMFORTABLE_WPM.get(lang, 120)
    measured = cpm if lang in CJK else wpm
    if measured <= 0:
        return "unknown"
    ratio = measured / target
    if ratio < 0.6:
        return "hesitant"
    if ratio > 1.25:
        return "fast"
    return "steady"


def analyze(learner_turns: list[dict[str, Any]], *, lang: str) -> FluencyReport:
    """`learner_turns`: [{idx, text, words: [Word|dict], duration_ms, response_delay_ms}]."""
    report = FluencyReport()
    delays: list[int] = []
    filler_totals: dict[str, int] = {}
    any_timings = False

    for turn in learner_turns:
        text = turn.get("text") or ""
        idx = int(turn.get("idx", 0))
        words_raw = turn.get("words") or []
        words = [w if isinstance(w, Word) else Word(**w) for w in words_raw]

        tokens = tokenize_words(text, lang)
        report.word_count += len(tokens) or len(words)
        report.char_count += count_chars(text)
        report.words_per_turn.append(len(tokens) or len(words))
        report.turns_measured += 1

        for filler, n in count_fillers(text, lang).items():
            filler_totals[filler] = filler_totals.get(filler, 0) + n

        if uses_native_language(text, lang):
            report.native_language_turns += 1

        delay = turn.get("response_delay_ms")
        if isinstance(delay, int) and delay >= 0:
            delays.append(delay)

        if words:
            any_timings = True
            report.speaking_seconds += max(
                words[-1].end - words[0].start, (turn.get("duration_ms") or 0) / 1000
            )
            for prev, nxt in itertools.pairwise(words):
                gap = nxt.start - prev.end
                if gap >= LONG_PAUSE_S:
                    report.long_pauses.append(Pause(prev.w, round(gap, 2), idx))
            for w in words:
                if w.prob < UNCLEAR_PROB and w.w.strip():
                    report.unclear_words.append(UnclearWord(w.w.strip(), idx, round(w.prob, 3)))
        elif turn.get("duration_ms"):
            any_timings = True
            report.speaking_seconds += turn["duration_ms"] / 1000

    report.filler_counts = dict(sorted(filler_totals.items(), key=lambda kv: -kv[1]))
    report.filler_total = sum(filler_totals.values())
    report.estimated_from_text = not any_timings

    if report.speaking_seconds > 0:
        minutes = report.speaking_seconds / 60
        report.words_per_minute = round(report.word_count / minutes, 1)
        report.chars_per_minute = round(report.char_count / minutes, 1)
    report.rate_label = _rate_label(report.words_per_minute, report.chars_per_minute, lang)

    if delays:
        report.avg_response_delay_ms = int(statistics.fmean(delays))
        report.max_response_delay_ms = max(delays)
    report.longest_pause_s = max((p.seconds for p in report.long_pauses), default=0.0)
    report.turn_length_trend = _trend(report.words_per_turn)

    # Worst-first, capped: the report shows at most five.
    report.long_pauses.sort(key=lambda p: -p.seconds)
    report.long_pauses = report.long_pauses[:5]
    report.unclear_words.sort(key=lambda u: u.probability)
    report.unclear_words = report.unclear_words[:8]
    report.speaking_seconds = round(report.speaking_seconds, 2)
    return report


def fluency_score(report: FluencyReport, *, level: str) -> float:
    """0-100 fluency sub-score, calibrated by level (plan §8.3).

    Deliberately simple and explainable: start from a level-appropriate base and
    deduct for the two things learners actually notice — long silences and
    filler density.  The report shows the components, never just the number.
    """
    base = {"A1": 70.0, "A2": 68.0, "B1": 64.0, "B2": 60.0}.get(level[:2], 65.0)

    rate_bonus = {"steady": 18.0, "fast": 10.0, "hesitant": 2.0, "unknown": 8.0}[report.rate_label]

    pause_penalty = min(
        18.0, sum(max(0.0, p.seconds - LONG_PAUSE_S) * 2.0 for p in report.long_pauses)
    )

    words = max(report.word_count, 1)
    filler_density = report.filler_total / words
    filler_penalty = min(12.0, filler_density * 120)

    delay_penalty = 0.0
    if report.avg_response_delay_ms:
        over = max(0, report.avg_response_delay_ms - 2500) / 1000
        delay_penalty = min(10.0, over * 2.5)

    return round(
        max(0.0, min(100.0, base + rate_bonus - pause_penalty - filler_penalty - delay_penalty)), 1
    )

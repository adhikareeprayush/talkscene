"""Building shadowing drill sets (plan §8.5, ADR 0003 track 2).

Azure's free tier allows 5 audio hours a month, so drills have to be *short*
and *chosen well*.  Priority order:

1. A phrase that contains a word the learner's audio suggested was unclear —
   the highest-value practice available, and the reason the passive track
   exists at all.
2. An AI line the learner heard in context, so the model sentence is one they
   already understand.
3. An authored `useful_phrase` from the scenario, as the floor.

Every drill carries a known reference text, which is what makes Azure's
*scripted* mode usable — its most reliable configuration.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.drill import Drill
from .fluency import FluencyReport

MAX_DRILLS = 4
MIN_CHARS = 4
MAX_CHARS = 60


def _usable(sentence: str) -> bool:
    text = sentence.strip()
    return MIN_CHARS <= len(text) <= MAX_CHARS


def _split(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?。．！？])\s*", text or "") if p.strip()]


def select_sentences(
    *,
    scenario: dict[str, Any],
    ai_lines: list[str],
    fluency: FluencyReport,
) -> list[dict[str, Any]]:
    """Returns `[{ref_text, translation_en, focus_words, source}]`, best first."""
    phrases = scenario.get("useful_phrases") or []
    unclear = [u.word for u in fluency.unclear_words]
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(text: str, source: str, focus: list[str], translation: str | None = None) -> None:
        clean = text.strip()
        if not _usable(clean) or clean in seen:
            return
        seen.add(clean)
        picked.append(
            {
                "ref_text": clean,
                "translation_en": translation,
                "focus_words": focus,
                "source": source,
            }
        )

    # 1. phrases and AI lines that contain a flagged word
    for word in unclear:
        for phrase in phrases:
            if word in phrase.get("text", ""):
                add(phrase["text"], "unclear_word", [word], phrase.get("meaning"))
                break
        else:
            for line in ai_lines:
                for sentence in _split(line):
                    if word in sentence:
                        add(sentence, "unclear_word", [word])
                        break
                if len(picked) >= MAX_DRILLS:
                    break
        if len(picked) >= MAX_DRILLS:
            break

    # 2. authored phrases, which also carry a translation
    for phrase in phrases:
        if len(picked) >= MAX_DRILLS:
            break
        add(phrase["text"], "scenario_phrase", [], phrase.get("meaning"))

    # 3. short AI lines as the floor
    for line in ai_lines:
        if len(picked) >= MAX_DRILLS:
            break
        for sentence in _split(line):
            add(sentence, "ai_line", [])

    return picked[:MAX_DRILLS]


async def create(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str | None,
    language: str,
    sentences: list[dict[str, Any]],
) -> list[Drill]:
    drills = [
        Drill(
            session_id=session_id,
            user_id=user_id,
            language=language,
            ref_text=item["ref_text"],
            translation_en=item.get("translation_en"),
            focus_words=item.get("focus_words") or None,
            # Initialised explicitly: once the row is flushed, reading an
            # untouched collection would be a lazy load from async code.
            attempts=[],
        )
        for item in sentences
    ]
    for drill in drills:
        db.add(drill)
    await db.flush()
    return drills

"""Politeness / register linter (plan §6.6, §8.2, §20.3).

Register is the error learners of Korean, Japanese and German get marked down
for in real life and that a generic grammar check misses entirely: a
grammatical sentence in the wrong politeness level is still wrong. This runs on
the learner's own utterances, compares them against the register the scenario's
persona implies, and reports *consistency* rather than a score.

It is deliberately heuristic — sentence-final morphology and pronoun choice —
and it reports `confidence`, because Korean and Japanese endings are genuinely
ambiguous out of context. Low confidence means the UI shows a note, not a
verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── expected register: declared by the pack, inferred only as a fallback ────
# The pack's `learner_register` is authoritative. Inference exists for packs
# that predate the field, and is deliberately narrow: it must not read the
# *character's* register as the learner's. Hotel staff speak 합쇼체 to guests;
# a guest answering in 해요체 is exactly right.
FORMAL_HINTS = re.compile(
    r"\binterview|면접|vorstellungsgespräch|bureaucratic|civil servant|bürgeramt|"
    r"\bclient\b|取引先|business keigo|\bHR\b",
    re.IGNORECASE,
)
CASUAL_HINTS = re.compile(
    r"반말|casual|informal|du-Form|duzt|friend|party|plain form|familiar|chatty",
    re.IGNORECASE,
)

# ── Korean ──────────────────────────────────────────────────────────────────
KO_FORMAL = (re.compile(r"(습니다|ㅂ니다|습니까|ㅂ니까|십시오|습니다만)\s*[.?!]?$", re.MULTILINE),)
KO_POLITE = (
    re.compile(r"(요|예요|이에요|세요|에요|죠|께요|을게요|ㄹ게요)\s*[.?!]?$", re.MULTILINE),
)
KO_CASUAL = (
    re.compile(r"(야|자|니|냐|거야|거든|더라|는데\?|했어|했지|해|이야|임)\s*[.?!]?$", re.MULTILINE),
)

# ── Japanese ────────────────────────────────────────────────────────────────
JA_FORMAL = (
    re.compile(r"(ございます|いたします|おります|ください|ませ)\s*[。．.!?]?$", re.MULTILINE),
)
JA_POLITE = (
    re.compile(
        r"(です|ます|ません|ました|でした|ましょう|ですか|ますか)\s*[。．.!?]?$", re.MULTILINE
    ),
)
JA_CASUAL = (
    re.compile(
        r"(だ|だよ|だね|じゃない|かな|よね|でしょ|ちゃう|してる|する|した|ない)\s*[。．.!?]?$",
        re.MULTILINE,
    ),
)

# ── German ──────────────────────────────────────────────────────────────────
DE_FORMAL = re.compile(r"\b(Sie|Ihnen|Ihren|Ihrem|Ihre|Ihr)\b")
DE_CASUAL = re.compile(r"\b(du|dich|dir|dein|deine|deinem|deinen|ihr|euch|euer)\b", re.IGNORECASE)

LEVEL_ORDER = ("casual", "polite", "formal")


@dataclass(slots=True)
class RegisterLint:
    language: str
    expected: str = "polite"  # casual | polite | formal
    detected: dict[str, int] = field(default_factory=dict)
    dominant: str = "unknown"
    consistent: bool = True
    confidence: str = "low"  # low | medium | high
    notes: str = ""
    offending_turns: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "expected": self.expected,
            "detected": self.detected,
            "dominant": self.dominant,
            "consistent": self.consistent,
            "confidence": self.confidence,
            "notes": self.notes,
            "offending_turns": self.offending_turns,
        }


def expected_register(persona_style: str, scenario_category: str = "") -> str:
    blob = f"{persona_style} {scenario_category}"
    if CASUAL_HINTS.search(blob):
        return "casual"
    if FORMAL_HINTS.search(blob):
        return "formal"
    return "polite"


def _too_casual(expected: str, levels: set[str]) -> bool:
    """Is every level in this turn below what the setting calls for?

    Ranked casual < polite < formal. A job interview expects formal, so a turn
    entirely in 해요체 is flagged even though it is perfectly polite.
    """
    floor = LEVEL_ORDER.index(expected)
    return all(level in LEVEL_ORDER and LEVEL_ORDER.index(level) < floor for level in levels)


def _classify_ko(text: str) -> str | None:
    for pattern in KO_FORMAL:
        if pattern.search(text):
            return "formal"
    for pattern in KO_POLITE:
        if pattern.search(text):
            return "polite"
    for pattern in KO_CASUAL:
        if pattern.search(text):
            return "casual"
    return None


def _classify_ja(text: str) -> str | None:
    for pattern in JA_FORMAL:
        if pattern.search(text):
            return "formal"
    for pattern in JA_POLITE:
        if pattern.search(text):
            return "polite"
    for pattern in JA_CASUAL:
        if pattern.search(text):
            return "casual"
    return None


def _classify_de(text: str) -> str | None:
    formal = len(DE_FORMAL.findall(text))
    casual = len(DE_CASUAL.findall(text))
    if formal > casual:
        return "formal"
    if casual > formal:
        return "casual"
    return None


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。．！？])\s*|\n+", text.strip())
    return [p.strip() for p in parts if p and p.strip()]


def lint(
    learner_turns: list[dict[str, Any]],
    *,
    lang: str,
    persona_style: str,
    category: str = "",
    expected: str | None = None,
) -> RegisterLint:
    expected = expected if expected in LEVEL_ORDER else expected_register(persona_style, category)
    result = RegisterLint(language=lang, expected=expected)

    if lang == "en":
        result.confidence = "low"
        result.notes = "English register is contextual; no automatic check is applied."
        return result

    classify = {"ko": _classify_ko, "ja": _classify_ja, "de": _classify_de}[lang]
    counts: dict[str, int] = {}
    offenders: list[int] = []

    for turn in learner_turns:
        text = turn.get("text") or ""
        idx = int(turn.get("idx", 0))
        turn_levels = {level for s in _sentences(text) if (level := classify(s)) is not None}
        for level in turn_levels:
            counts[level] = counts.get(level, 0) + 1
        # Mixing two levels inside one turn is the clearest signal of trouble.
        if (
            len(turn_levels) > 1
            or (turn_levels and _too_casual(expected, turn_levels))
            or (turn_levels and expected == "casual" and "formal" in turn_levels)
        ):
            offenders.append(idx)

    result.detected = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    classified = sum(counts.values())
    result.dominant = max(counts, key=lambda k: counts[k]) if counts else "unknown"
    result.offending_turns = sorted(set(offenders))[:8]
    result.consistent = not result.offending_turns

    if classified == 0:
        result.confidence = "low"
    elif classified >= 6:
        result.confidence = "high"
    else:
        result.confidence = "medium"

    result.notes = _note(lang, expected, result)
    return result


def _note(lang: str, expected: str, result: RegisterLint) -> str:
    if result.confidence == "low":
        return "Too few complete sentences to judge the politeness level."
    if result.consistent:
        labels = {
            "ko": {"formal": "합쇼체", "polite": "해요체", "casual": "반말"},
            "ja": {"formal": "敬語", "polite": "です/ます", "casual": "plain form"},
            "de": {"formal": "Sie", "polite": "Sie", "casual": "du"},
        }[lang]
        return f"You stayed in {labels.get(result.dominant, result.dominant)} throughout — exactly right here."
    advice = {
        "ko": {
            "formal": "This setting expects 합쇼체 (-습니다/-십니까). 해요체 and 반말 both sound too casual here.",
            "polite": "Keep to 해요체. 반말 endings (-야, -했어) read as over-familiar with staff.",
            "casual": "With a friend, 반말 is fine — switching to 해요체 mid-conversation creates distance.",
        },
        "ja": {
            "formal": "This setting expects 敬語/丁寧語. Plain forms (する, だ) sound abrupt to a client.",
            "polite": "Stay in です/ます. Plain form mid-conversation reads as talking down.",
            "casual": "Plain form fits here; です/ます makes it oddly stiff.",
        },
        "de": {
            "formal": "Stay with Sie throughout. Switching to du is a register error in this setting.",
            "polite": "Stay with Sie — mixing in du is noticeable.",
            "casual": "du is right here; Sie with a peer at a party sounds cold or sarcastic.",
        },
    }[lang]
    return advice.get(expected, "") + f" Turns to review: {_join_turns(result.offending_turns)}."


def _join_turns(turns: list[int]) -> str:
    """[1, 3, 5] -> "1, 3 and 5" - this is read by a learner, not a developer."""
    names = [str(t) for t in turns]
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"

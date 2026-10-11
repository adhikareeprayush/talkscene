"""Content checks for learner-authored scenarios (plan §6.6, §15).

Only custom scenarios go through this: the shipped packs are reviewed content.
It is a pre-filter, not the whole defence — the generation prompt also instructs
the model to refuse, and refusal from either layer blocks the save.

Deliberately narrow: it targets the four categories the plan names (harassment,
sexual content, self-harm roleplay, illegal activity) plus impersonation of a
real identifiable person.  Over-broad blocking would reject legitimate practice
— an argument with a landlord, reporting a theft, a medical consultation are
all normal things an adult learner needs to rehearse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_REQUEST_CHARS = 600


@dataclass(slots=True)
class ModerationResult:
    allowed: bool
    category: str = ""
    reason: str = ""


_RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "sexual",
        re.compile(
            r"\b(sexual|sex scene|erotic|nude|nudes|naked|porn|fetish|seduce|"
            r"intimate roleplay|bedroom roleplay)\b",
            re.IGNORECASE,
        ),
        "Sexual roleplay is not supported.",
    ),
    (
        "minors",
        re.compile(
            r"\b(child|children|kid|kids|minor|minors|underage|teen|teenager|schoolgirl|schoolboy)\b"
            r"(?=[^.]{0,80}\b(date|dating|romance|romantic|kiss|flirt|sexual|sex)\b)",
            re.IGNORECASE,
        ),
        "Scenarios involving minors in romantic or sexual situations are not supported.",
    ),
    (
        "harassment",
        re.compile(
            r"\b(racist|racial slur|slurs?|hate speech|humiliate|degrade|bully|bullying|"
            r"insult (?:me|them|him|her)|verbally abuse)\b",
            re.IGNORECASE,
        ),
        "Scenarios built around abuse or slurs are not supported.",
    ),
    (
        "self_harm",
        re.compile(
            r"\b(suicide|suicidal|kill myself|self[- ]harm|cutting myself|starve myself|"
            r"how to die|end my life)\b",
            re.IGNORECASE,
        ),
        "This topic needs a person, not a language-practice bot. "
        "If you are struggling, please contact a local crisis line.",
    ),
    (
        "illegal",
        re.compile(
            r"\b(buy (?:drugs|cocaine|heroin|meth)|sell drugs|launder money|money laundering|"
            r"build a bomb|make explosives|hack(?:ing)? (?:into|an account)|steal a car|"
            r"forge (?:a )?(?:passport|document|id)|human trafficking)\b",
            re.IGNORECASE,
        ),
        "Scenarios about committing crimes are not supported.",
    ),
    (
        "impersonation",
        re.compile(
            r"\b(?:pretend to be|roleplay as|act as|impersonate)\s+(?:the\s+)?"
            r"(?:real\s+)?(?:president|prime minister|ceo of|my (?:boss|ex|therapist|doctor)\b)",
            re.IGNORECASE,
        ),
        "Impersonating a specific real person is not supported. "
        'Describe the role instead (e.g. "a company director").',
    ),
]


def check_scenario_request(text: str) -> ModerationResult:
    request = (text or "").strip()
    if not request:
        return ModerationResult(False, "empty", "Describe the situation you want to practise.")
    if len(request) > MAX_REQUEST_CHARS:
        return ModerationResult(
            False, "too_long", f"Keep the description under {MAX_REQUEST_CHARS} characters."
        )
    for category, pattern, reason in _RULES:
        if pattern.search(request):
            return ModerationResult(False, category, reason)
    return ModerationResult(True)


def check_generated_scenario(doc: dict) -> ModerationResult:
    """Second pass over what the model produced, in case the prompt was bypassed."""
    if refusal := doc.get("refused"):
        return ModerationResult(False, "model_refused", str(refusal)[:300])
    blob = " ".join(
        str(part)
        for part in (
            doc.get("summary", ""),
            doc.get("setting", ""),
            doc.get("user_role", ""),
            (doc.get("persona") or {}).get("role", ""),
            (doc.get("persona") or {}).get("style", ""),
            " ".join(g.get("text", "") for g in (doc.get("goals") or [])),
        )
    )
    return check_scenario_request(blob[:MAX_REQUEST_CHARS])

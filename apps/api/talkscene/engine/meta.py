"""Parsing the `###META` tail of a roleplay reply.

The model streams the spoken line first and the metadata after a delimiter, so
TTS can start on sentence one.  That means the tail has to be recovered from a
stream that may be truncated, may have no delimiter at all, or may wrap the
JSON in a code fence.  All three are handled here, and a failure degrades to
"no metadata" rather than losing the reply.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")
_DELIM = re.compile(r"#{2,4}\s*META\s*", re.IGNORECASE)


@dataclass(slots=True)
class TurnMeta:
    goals_done: list[str] = field(default_factory=list)
    translation_en: str = ""
    romanization: str = ""
    suggested_replies: list[str] = field(default_factory=list)
    end: bool = False
    parsed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "goals_done": self.goals_done,
            "translation_en": self.translation_en,
            "romanization": self.romanization,
            "suggested_replies": self.suggested_replies,
            "end": self.end,
        }


def split_reply(raw: str) -> tuple[str, str]:
    """(spoken reply, raw metadata tail).  Tail is '' when there is no delimiter."""
    match = _DELIM.search(raw)
    if not match:
        return raw.strip(), ""
    return raw[: match.start()].strip(), raw[match.end() :].strip()


def _coerce_strings(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:limit]:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            # Models sometimes return [{"text": "..."}] for suggested_replies.
            text = item.get("text") or item.get("reply")
            if isinstance(text, str) and text.strip():
                out.append(text.strip())
    return out


def parse_meta(tail: str) -> TurnMeta:
    if not tail:
        return TurnMeta()
    cleaned = _FENCE.sub("", tail).strip()
    # Trailing commentary after the object is common; keep the first object only.
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        cleaned = cleaned[start:] if start >= 0 else cleaned
    depth = 0
    end = -1
    for i, ch in enumerate(cleaned):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end > 0:
        cleaned = cleaned[:end]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return TurnMeta()
    if not isinstance(data, dict):
        return TurnMeta()

    return TurnMeta(
        goals_done=_coerce_strings(data.get("goals_done"), 12),
        translation_en=str(data.get("translation_en") or "").strip()[:600],
        romanization=str(data.get("romanization") or "").strip()[:600],
        suggested_replies=_coerce_strings(data.get("suggested_replies"), 3),
        end=bool(data.get("end")),
        parsed=True,
    )


def parse_json_object(raw: str) -> dict[str, Any] | None:
    """Tolerant JSON-object extraction for the feedback / explain / scenario calls."""
    if not raw:
        return None
    cleaned = _FENCE.sub("", raw).strip()
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    stop = cleaned.rfind("}")
    if start < 0 or stop <= start:
        return None
    try:
        value = json.loads(cleaned[start : stop + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None

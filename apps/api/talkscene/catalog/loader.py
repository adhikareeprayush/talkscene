"""Loading scenario packs from `packages/scenarios` into the database.

The YAML files are the authoring format and the source of truth in git; the
`scenarios` table is a queryable projection of them.  `sync()` is idempotent and
safe to run on every boot in development: a pack is rewritten when its
`version` increases, left alone when it has not changed, and unpublished when
its file disappears, so a deleted scenario stops appearing in the catalog
without orphaning the sessions that referenced it.

Validation happens here too, against the same `schema.json` the Node validator
uses, so an invalid pack cannot reach the API even if CI was skipped.
"""

from __future__ import annotations

import functools
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..models.scenario import Scenario, ScenarioTag

log = logging.getLogger("talkscene.catalog")


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    unpublished: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "unpublished": self.unpublished,
            "errors": self.errors,
        }


def packs_root() -> Path:
    return Path(settings.scenario_packs_dir)


@functools.lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads((packs_root() / "schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate_doc(doc: dict[str, Any]) -> list[str]:
    """Schema errors for one scenario document, most structural first."""
    errors = sorted(_validator().iter_errors(doc), key=lambda e: list(e.path))
    return [f"{list(e.path) or '/'}: {e.message}" for e in errors]


def load_file(path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("scenario file must contain a single YAML mapping")
    if errors := validate_doc(doc):
        raise ValueError("; ".join(errors[:4]))
    return doc


def discover() -> list[Path]:
    root = packs_root() / "packs"
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.y*ml") if p.is_file())


async def sync(db: AsyncSession, *, only_published: bool = True) -> SyncResult:
    result = SyncResult()
    seen: set[str] = set()

    for path in discover():
        rel = path.relative_to(packs_root())
        try:
            doc = load_file(path)
        except Exception as exc:
            result.errors.append(f"{rel}: {exc}")
            continue

        status = doc.get("status", "draft")
        if only_published and status != "published":
            continue

        seen.add(doc["id"])
        row = await db.get(Scenario, doc["id"])
        if row is None:
            db.add(_to_row(doc))
            result.created += 1
        elif row.version != doc["version"] or row.yaml != doc:
            _update_row(row, doc)
            # Tags are a child table, so replace rather than merge.
            for tag in list(row.tags):
                await db.delete(tag)
            await db.flush()
            row.tags = [ScenarioTag(scenario_id=row.id, tag=t) for t in doc.get("tags", [])]
            result.updated += 1
        else:
            result.unchanged += 1

    # A pack removed from git should vanish from the catalog, but its rows are
    # still referenced by past sessions - so unpublish instead of deleting.
    if seen:
        stale = await db.scalars(
            select(Scenario).where(Scenario.is_published.is_(True), Scenario.id.not_in(seen))
        )
        for row in stale:
            row.is_published = False
            result.unpublished += 1

    await db.flush()
    log.info("scenario sync complete", extra={"extra_fields": result.as_dict()})
    return result


def _to_row(doc: dict[str, Any]) -> Scenario:
    row = Scenario(id=doc["id"])
    _update_row(row, doc)
    row.tags = [ScenarioTag(scenario_id=doc["id"], tag=t) for t in doc.get("tags", [])]
    return row


def _update_row(row: Scenario, doc: dict[str, Any]) -> None:
    row.version = doc["version"]
    row.language = doc["language"]
    row.level = doc["level"]
    row.category = doc["category"]
    row.title_en = doc["title"]["en"]
    row.summary = doc["summary"]
    row.yaml = doc
    row.is_published = doc.get("status", "draft") == "published"


# ── read helpers used by the API ────────────────────────────────────────────
LANGUAGE_INFO: dict[str, dict[str, Any]] = {
    "ko": {
        "code": "ko",
        "name": "Korean",
        "native_name": "한국어",
        "flag": "🇰🇷",
        "accent": "coral",
        "romanization": True,
        "furigana": False,
        "pronunciation_assessment": True,
        "premium_tts": True,
        "note": "Premium Korean voices come from Azure; Deepgram Aura-2 has no Korean voice.",
    },
    "ja": {
        "code": "ja",
        "name": "Japanese",
        "native_name": "日本語",
        "flag": "🇯🇵",
        "accent": "indigo",
        "romanization": True,
        "furigana": True,
        "pronunciation_assessment": True,
        "premium_tts": True,
        "note": "",
    },
    "de": {
        "code": "de",
        "name": "German",
        "native_name": "Deutsch",
        "flag": "🇩🇪",
        "accent": "amber",
        "romanization": False,
        "furigana": False,
        "pronunciation_assessment": True,
        "premium_tts": True,
        "note": "",
    },
    "en": {
        "code": "en",
        "name": "English",
        "native_name": "English",
        "flag": "🇬🇧",
        "accent": "teal",
        "romanization": False,
        "furigana": False,
        "pronunciation_assessment": True,
        "premium_tts": True,
        "note": "",
    },
}

CATEGORIES = (
    "travel",
    "food",
    "shopping",
    "health",
    "services",
    "social",
    "work",
    "culture",
    "emergencies",
)
LEVELS = ("A1", "A2", "B1", "B2")


def brief(doc: dict[str, Any]) -> dict[str, Any]:
    """The pre-chat brief: everything the learner sees before starting (§11.3 D)."""
    return {
        "id": doc["id"],
        "version": doc["version"],
        "language": doc["language"],
        "level": doc["level"],
        "category": doc["category"],
        "icon": doc.get("icon"),
        "title": doc["title"],
        "summary": doc["summary"],
        "persona": doc["persona"],
        "setting": doc["setting"],
        "user_role": doc["user_role"],
        "goals": [{"id": g["id"], "text": g["text"]} for g in doc["goals"]],
        "target_vocab": doc.get("target_vocab", []),
        "target_grammar": doc.get("target_grammar", []),
        "useful_phrases": doc.get("useful_phrases", []),
        "cultural_notes": doc.get("cultural_notes", []),
        "turn_limits": doc["turn_limits"],
        "estimated_minutes": estimated_minutes(doc),
        "tags": doc.get("tags", []),
        "voice": doc.get("voice", {}),
        "learner_register": doc.get("learner_register"),
    }


def card(doc: dict[str, Any]) -> dict[str, Any]:
    """The library card: the subset the list view needs (§11.3 C)."""
    return {
        "id": doc["id"],
        "language": doc["language"],
        "level": doc["level"],
        "category": doc["category"],
        "icon": doc.get("icon"),
        "title": doc["title"],
        "summary": doc["summary"],
        "estimated_minutes": estimated_minutes(doc),
        "tags": doc.get("tags", []),
    }


def estimated_minutes(doc: dict[str, Any]) -> int:
    """Rough duration: each exchange runs ~35 s of talking and thinking."""
    turns = doc["turn_limits"]["default"]
    return max(3, round(turns * 35 / 60))

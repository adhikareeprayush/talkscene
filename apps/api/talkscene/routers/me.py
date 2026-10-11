"""Profile, preferences, BYOK keys, data export and deletion (plan §11.3 J, §15)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import select

from ..core.crypto import seal_map, unseal_map
from ..core.errors import not_found
from ..core.storage import get_storage
from ..deps import Account, CurrentUser, Db
from ..models.drill import Drill
from ..models.report import Report
from ..models.session import PracticeSession
from ..models.user import UserPref
from ..models.vocab import VocabItem
from ..schemas.auth import Me, MeUpdate, Prefs
from ..schemas.common import Ok, problem_responses

router = APIRouter(prefix="/v1", tags=["me"])

BYOK_FIELDS = ("groq", "xai", "gemini", "deepgram", "azure_speech_key", "azure_speech_region")


def _to_me(user: Any) -> Me:
    prefs = user.prefs or UserPref.defaults(user.id)
    return Me(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_guest=user.is_guest,
        plan=user.plan,
        native_lang=user.native_lang,
        ui_lang=user.ui_lang,
        target_lang=user.target_lang,
        level=user.level,
        goals=user.goals or [],
        daily_goal_minutes=user.daily_goal_minutes,
        streak_days=user.streak_days,
        prefs=Prefs(
            tts_provider=prefs.tts_provider,
            tts_rate=prefs.tts_rate,
            show_romanization=prefs.show_romanization,
            show_furigana=prefs.show_furigana,
            show_translation=prefs.show_translation,
            mic_mode=prefs.mic_mode,
            correction_style=prefs.correction_style,
            keep_audio=prefs.keep_audio,
            theme=prefs.theme,
        ),
        byok_configured=sorted(unseal_map(prefs.byok_keys_encrypted).keys()),
    )


@router.get("/me", response_model=Me, summary="Profile and preferences")
async def get_me(user: CurrentUser) -> Me:
    return _to_me(user)


@router.patch(
    "/me",
    response_model=Me,
    summary="Update profile, preferences or BYOK keys",
    description=(
        "BYOK keys are encrypted at rest and never returned — only the provider names appear in "
        "`byok_configured`. Sending an empty string for a provider removes its key."
    ),
    responses=problem_responses(401, 422),
)
async def patch_me(body: MeUpdate, user: CurrentUser, db: Db) -> Me:
    for field in (
        "display_name",
        "native_lang",
        "ui_lang",
        "target_lang",
        "level",
        "goals",
        "daily_goal_minutes",
    ):
        value = getattr(body, field)
        if value is not None:
            setattr(user, field, value)

    prefs = user.prefs or UserPref.defaults(user.id)
    if user.prefs is None:
        db.add(prefs)
        user.prefs = prefs
    if body.prefs is not None:
        for field, value in body.prefs.model_dump(exclude_none=True).items():
            setattr(prefs, field, value)

    if body.byok is not None:
        supplied = body.byok.model_dump(exclude_none=True)
        current = unseal_map(prefs.byok_keys_encrypted)
        for name in BYOK_FIELDS:
            if name in supplied:
                if supplied[name].strip():
                    current[name] = supplied[name].strip()
                else:
                    current.pop(name, None)
        prefs.byok_keys_encrypted = seal_map(current) or None
        user.plan = "byok" if current else ("free" if user.plan == "byok" else user.plan)

    await db.flush()
    return _to_me(user)


@router.get(
    "/me/export",
    summary="Export all of this account's data",
    description=(
        "GDPR/CCPA data portability (plan §15). Audio is excluded: it is ephemeral by design."
    ),
    responses=problem_responses(401, 403),
)
async def export_data(user: Account, db: Db) -> dict[str, Any]:
    sessions = list(
        await db.scalars(select(PracticeSession).where(PracticeSession.user_id == user.id))
    )
    reports = list(
        await db.scalars(
            select(Report).where(Report.session_id.in_([s.id for s in sessions] or [""]))
        )
    )
    vocab = list(await db.scalars(select(VocabItem).where(VocabItem.user_id == user.id)))
    drills = list(await db.scalars(select(Drill).where(Drill.user_id == user.id)))

    return {
        "exported_at": dt.datetime.now(dt.UTC).isoformat(),
        "profile": _to_me(user).model_dump(),
        "sessions": [
            {
                "id": s.id,
                "scenario_id": s.scenario_id,
                "language": s.language,
                "level": s.level,
                "status": s.status,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "goals_state": s.goals_state,
                "turns": [
                    {
                        "idx": t.idx,
                        "role": t.role,
                        "text": t.text,
                        "translation_en": t.translation_en,
                    }
                    for t in sorted(s.turns, key=lambda t: t.idx)
                ],
            }
            for s in sessions
        ],
        "reports": [r.json for r in reports],
        "vocabulary": [
            {
                "language": v.language,
                "term": v.term,
                "reading": v.reading,
                "meaning": v.meaning,
                "example": v.example,
            }
            for v in vocab
        ],
        "drills": [
            {
                "language": d.language,
                "ref_text": d.ref_text,
                "best_accuracy": d.best_accuracy,
                "attempts": [
                    {
                        "attempt": a.attempt,
                        "accuracy": a.accuracy,
                        "fluency": a.fluency,
                        "completeness": a.completeness,
                        "prosody": a.prosody,
                        "provider": a.provider,
                    }
                    for a in d.attempts
                ],
            }
            for d in drills
        ],
    }


@router.delete(
    "/me",
    status_code=status.HTTP_200_OK,
    response_model=Ok,
    summary="Delete this account and all of its data",
    responses=problem_responses(401, 404),
)
async def delete_me(user: CurrentUser, db: Db) -> Ok:
    if user.deleted_at is not None:
        raise not_found("Account")

    # Remove stored audio first: the rows carry the only pointers to it.
    storage = get_storage()
    sessions = list(
        await db.scalars(select(PracticeSession).where(PracticeSession.user_id == user.id))
    )
    for session in sessions:
        for turn in session.turns:
            for key in turn.audio_keys or ([turn.audio_key] if turn.audio_key else []):
                await storage.delete(key)
    for drill in await db.scalars(select(Drill).where(Drill.user_id == user.id)):
        for attempt in drill.attempts:
            if attempt.audio_key:
                await storage.delete(attempt.audio_key)

    await db.delete(user)  # cascades to prefs, sessions, turns, vocab, drills
    await db.flush()
    return Ok(detail="Account and all associated data deleted.")

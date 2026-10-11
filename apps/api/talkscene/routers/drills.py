"""Shadowing drills and pronunciation scoring (plan §8.5, §11.3 G; ADR 0003).

Guests can drill — the report creates these sentences for them, so locking
them out of their own drill set would be incoherent.  Saving vocabulary is the
feature that requires an account.

This is the only place in the product that produces a real pronunciation score,
and only in Azure's scripted mode against a known reference text.  When Azure
is unavailable the heuristic provider answers instead and every response says
`authoritative: false`, which the UI must surface rather than round away.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, File, Query, Request, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..core.audio import estimate_duration_s, ffmpeg_path
from ..core.config import settings
from ..core.errors import audio_too_large, forbidden, not_found, quota_exceeded, unprocessable
from ..core.ratelimit import Limit
from ..core.storage import drill_audio_key, get_storage
from ..deps import CurrentUser, Db, Router, throttle
from ..engine import drills as drill_builder
from ..engine import fluency as fluency_mod
from ..engine import speech
from ..models.drill import Drill, DrillAttempt
from ..models.report import Report
from ..models.scenario import Scenario
from ..models.session import PracticeSession
from ..models.usage import UsageLedger
from ..schemas.common import Ok, problem_responses
from ..schemas.learning import CreateDrillsRequest, DrillQuota, DrillSet
from ..schemas.learning import Drill as DrillSchema
from ..schemas.learning import DrillAttempt as AttemptSchema
from ..schemas.learning import WordScore as WordScoreSchema

router = APIRouter(prefix="/v1/drills", tags=["drills"])

ATTEMPT_LIMIT = Limit(count=20, per_s=300)
MAX_DRILL_SECONDS = 15


# ── serialisation ───────────────────────────────────────────────────────────
def attempt_out(attempt: DrillAttempt) -> AttemptSchema:
    result = attempt.result or {}
    return AttemptSchema(
        id=attempt.id,
        attempt=attempt.attempt,
        provider=attempt.provider,
        accuracy=attempt.accuracy,
        fluency=attempt.fluency,
        completeness=attempt.completeness,
        prosody=attempt.prosody,
        recognized_text=attempt.recognized_text,
        words=[WordScoreSchema(**w) for w in result.get("words", [])],
        authoritative=bool(result.get("authoritative", False)),
        audio_url=(
            f"/v1/drills/{attempt.drill_id}/attempts/{attempt.attempt}/audio"
            if attempt.audio_key
            else None
        ),
        created_at=attempt.created_at,
    )


def drill_out(drill: Drill) -> DrillSchema:
    return DrillSchema(
        id=drill.id,
        language=drill.language,
        ref_text=drill.ref_text,
        translation_en=drill.translation_en,
        focus_words=drill.focus_words or [],
        reference_audio_url=f"/v1/drills/{drill.id}/reference-audio",
        best_accuracy=drill.best_accuracy,
        attempts=[attempt_out(a) for a in drill.attempts],
    )


async def drill_seconds_used(db: Db, user_id: str) -> int:
    start = dt.datetime.now(dt.UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(
        await db.scalar(
            select(func.coalesce(func.sum(UsageLedger.amount), 0.0)).where(
                UsageLedger.user_id == user_id,
                UsageLedger.capability == "pron",
                UsageLedger.unit == "seconds",
                UsageLedger.ts >= start,
            )
        )
        or 0
    )


async def _quota(db: Db, user_id: str, provider_router: Router) -> DrillQuota:
    used = await drill_seconds_used(db, user_id)
    limit = settings.quota_drill_seconds_per_month
    health = await provider_router.health()
    azure_ok = any(
        h.provider == "azure" and h.capability == "pron" and h.state == "ok" for h in health
    )
    note = ""
    if not azure_ok:
        note = "Azure Pronunciation Assessment is not configured, so scores are estimates only."
    elif not ffmpeg_path():
        note = "ffmpeg is not installed, so audio cannot be converted for phoneme scoring."
        azure_ok = False
    elif limit and used >= limit:
        note = (
            "Monthly pronunciation-scoring budget is spent; scores are estimates until it resets."
        )
        azure_ok = False
    return DrillQuota(
        seconds_used_this_month=used,
        seconds_limit=limit,
        authoritative_scoring_available=azure_ok,
        note=note,
    )


# ── create ──────────────────────────────────────────────────────────────────
@router.post(
    "",
    response_model=DrillSet,
    status_code=status.HTTP_201_CREATED,
    summary="Create a drill set from a report, or from your own sentences",
    responses=problem_responses(401, 403, 404, 422),
)
async def create_drills(
    body: CreateDrillsRequest, user: CurrentUser, db: Db, provider_router: Router
) -> DrillSet:
    if body.session_id:
        session = await db.scalar(
            select(PracticeSession)
            .where(PracticeSession.id == body.session_id)
            .options(selectinload(PracticeSession.turns))
        )
        if session is None:
            raise not_found("Session")
        if session.user_id != user.id:
            raise forbidden("This session belongs to another account.")

        # Reuse the drills the report already created, if it has run.
        report = await db.scalar(select(Report).where(Report.session_id == session.id))
        if report is not None:
            existing = list(
                await db.scalars(
                    select(Drill)
                    .where(Drill.session_id == session.id)
                    .options(selectinload(Drill.attempts))
                )
            )
            if existing:
                return DrillSet(
                    drills=[drill_out(d) for d in existing],
                    quota=await _quota(db, user.id, provider_router),
                )

        scenario_row = await db.get(Scenario, session.scenario_id)
        if scenario_row is None:
            raise not_found("Scenario")
        learner_turns = [
            {
                "idx": t.idx,
                "text": t.text,
                "words": t.stt_words or [],
                "duration_ms": t.duration_ms,
                "response_delay_ms": t.response_delay_ms,
            }
            for t in session.turns
            if t.role == "user"
        ]
        plan = drill_builder.select_sentences(
            scenario=scenario_row.yaml,
            ai_lines=[t.text for t in session.turns if t.role == "ai" and t.text],
            fluency=fluency_mod.analyze(learner_turns, lang=session.language),
        )
        created = await drill_builder.create(
            db,
            user_id=user.id,
            session_id=session.id,
            language=session.language,
            sentences=plan,
        )
    else:
        if not body.sentences or not body.language:
            raise unprocessable("Provide either `session_id`, or `sentences` with a `language`.")
        created = await drill_builder.create(
            db,
            user_id=user.id,
            session_id=None,
            language=body.language,
            sentences=[
                {"ref_text": s.strip(), "translation_en": None, "focus_words": []}
                for s in body.sentences
                if s.strip()
            ],
        )

    if not created:
        raise unprocessable("Nothing suitable to drill from this session yet.")
    return DrillSet(
        drills=[drill_out(d) for d in created], quota=await _quota(db, user.id, provider_router)
    )


@router.get(
    "",
    response_model=DrillSet,
    summary="List your drills",
    responses=problem_responses(401, 403),
)
async def list_drills(
    user: CurrentUser,
    db: Db,
    provider_router: Router,
    session_id: Annotated[str | None, Query()] = None,
    language: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> DrillSet:
    stmt = (
        select(Drill)
        .where(Drill.user_id == user.id)
        .options(selectinload(Drill.attempts))
        .order_by(Drill.created_at.desc())
        .limit(limit)
    )
    if session_id:
        stmt = stmt.where(Drill.session_id == session_id)
    if language:
        stmt = stmt.where(Drill.language == language)
    rows = list(await db.scalars(stmt))
    return DrillSet(
        drills=[drill_out(d) for d in rows], quota=await _quota(db, user.id, provider_router)
    )


async def _load_drill(db: Db, drill_id: str, user_id: str) -> Drill:
    drill = await db.scalar(
        select(Drill).where(Drill.id == drill_id).options(selectinload(Drill.attempts))
    )
    if drill is None:
        raise not_found("Drill")
    if drill.user_id != user_id:
        raise forbidden("This drill belongs to another account.")
    return drill


@router.get(
    "/{drill_id}",
    response_model=DrillSchema,
    summary="One drill with its attempts",
    responses=problem_responses(401, 403, 404),
)
async def get_drill(drill_id: str, user: CurrentUser, db: Db) -> DrillSchema:
    return drill_out(await _load_drill(db, drill_id, user.id))


# ── attempts ────────────────────────────────────────────────────────────────
@router.post(
    "/{drill_id}/attempts",
    response_model=AttemptSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a recording and get it scored",
    responses=problem_responses(401, 403, 404, 413, 422, 429),
)
async def create_attempt(
    drill_id: str,
    request: Request,
    user: CurrentUser,
    db: Db,
    provider_router: Router,
    audio: Annotated[UploadFile, File(description="webm/opus or wav, under 15 s.")],
) -> AttemptSchema:
    await throttle(request, user, scope="drill:attempt", limit=ATTEMPT_LIMIT)
    drill = await _load_drill(db, drill_id, user.id)

    data = await audio.read()
    if len(data) > settings.max_audio_bytes:
        raise audio_too_large(settings.max_audio_bytes)
    duration = estimate_duration_s(data, audio.content_type or "audio/webm")
    if duration > MAX_DRILL_SECONDS * 1.5:
        raise unprocessable(f"Drill recordings must be under {MAX_DRILL_SECONDS} seconds.")

    limit = settings.quota_drill_seconds_per_month
    if limit:
        used = await drill_seconds_used(db, user.id)
        if used >= limit:
            raise quota_exceeded(
                "pronunciation scoring", limit=limit, resets_at="the 1st of next month"
            )

    result = await provider_router.assess(
        data,
        lang=drill.language,
        reference_text=drill.ref_text,
        content_type=audio.content_type or "audio/webm",
        user_id=user.id,
        duration_s=duration,
    )

    number = len(drill.attempts) + 1
    key = drill_audio_key(drill.id, number, "wav" if data[:4] == b"RIFF" else "webm")
    await get_storage().put(key, data, audio.content_type or "audio/webm")

    attempt = DrillAttempt(
        drill_id=drill.id,
        attempt=number,
        audio_key=key,
        provider=result.provider,
        accuracy=result.accuracy,
        fluency=result.fluency,
        completeness=result.completeness,
        prosody=result.prosody,
        recognized_text=result.recognized_text,
        result=result.as_dict(),
    )
    db.add(attempt)
    # Keep the learner's best score, not their latest (plan §8.5).
    if drill.best_accuracy is None or result.accuracy > drill.best_accuracy:
        drill.best_accuracy = result.accuracy
    await db.flush()
    return attempt_out(attempt)


@router.get(
    "/{drill_id}/attempts/{number}/audio",
    summary="Play back one of your attempts",
    response_class=Response,
    responses={200: {"content": {"audio/webm": {}}}, **problem_responses(401, 403, 404)},
)
async def get_attempt_audio(drill_id: str, number: int, user: CurrentUser, db: Db) -> Response:
    drill = await _load_drill(db, drill_id, user.id)
    attempt = next((a for a in drill.attempts if a.attempt == number), None)
    if attempt is None or not attempt.audio_key:
        raise not_found("Attempt audio")
    data = await get_storage().get(attempt.audio_key)
    if data is None:
        raise not_found("Attempt audio (it may have passed its retention window)")
    media = "audio/wav" if data[:4] == b"RIFF" else "audio/webm"
    return Response(data, media_type=media, headers={"Cache-Control": "private, max-age=3600"})


@router.get(
    "/{drill_id}/reference-audio",
    summary="Hear the model sentence",
    description="Cached per sentence and voice, so repeated listening costs nothing.",
    response_class=Response,
    responses={200: {"content": {"audio/mpeg": {}}}, **problem_responses(401, 403, 404, 503)},
)
async def get_reference_audio(
    drill_id: str,
    user: CurrentUser,
    db: Db,
    provider_router: Router,
    rate: Annotated[float, Query(ge=0.5, le=1.5)] = 1.0,
) -> Response:
    drill = await _load_drill(db, drill_id, user.id)
    result = await speech.synthesize(
        db,
        provider_router,
        drill.ref_text,
        lang=drill.language,
        rate=rate,
        user_id=user.id,
        tier="premium",
    )
    if result is None:
        raise not_found("Reference audio (premium voice budget is spent)")
    chunk, key = result
    if drill.reference_audio_key != key:
        drill.reference_audio_key = key
        await db.flush()
    return Response(
        chunk.data,
        media_type=chunk.content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.delete(
    "/{drill_id}",
    response_model=Ok,
    summary="Delete a drill and its recordings",
    responses=problem_responses(401, 403, 404),
)
async def delete_drill(drill_id: str, user: CurrentUser, db: Db) -> Ok:
    drill = await _load_drill(db, drill_id, user.id)
    storage = get_storage()
    for attempt in drill.attempts:
        if attempt.audio_key:
            await storage.delete(attempt.audio_key)
    await db.delete(drill)
    await db.flush()
    return Ok(detail="Drill deleted.")

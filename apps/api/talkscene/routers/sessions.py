"""Sessions, turns, hints and audio — the conversation surface (plan §10.1, §10.2).

The turn endpoint accepts `text` as JSON or `audio` as multipart and answers
with `text/event-stream` in both cases, so the client has one code path.  The
SSE generator opens its own database session: FastAPI's request-scoped session
would be committed before the stream had finished writing to it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..core.config import settings
from ..core.db import get_sessionmaker
from ..core.errors import ProblemError, forbidden, not_found, unprocessable
from ..core.ratelimit import Limit
from ..core.storage import get_storage
from ..deps import CurrentUser, Db, Router, enforce_session_quota, throttle
from ..engine.orchestrator import Orchestrator, SseEvent
from ..models.report import Report
from ..models.scenario import Scenario
from ..models.session import PracticeSession, Turn
from ..providers.registry import get_router
from ..schemas.catalog import GoalState
from ..schemas.common import Page, problem_responses
from ..schemas.session import (
    EndSessionResponse,
    HintRequest,
    HintResponse,
    SessionDetail,
    SessionOptions,
    SessionState,
    SessionSummary,
    StartSessionRequest,
    StartSessionResponse,
    SubmitTurnRequest,
    TurnOut,
)

log = logging.getLogger("talkscene.sessions")
router = APIRouter(prefix="/v1/sessions", tags=["sessions"])

TURN_LIMIT = Limit(count=40, per_s=60)
HINT_LIMIT = Limit(count=30, per_s=60)
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Nginx buffers event streams by default, which would hold every token back
    # until the turn finished.
    "X-Accel-Buffering": "no",
}


# ── serialisation ───────────────────────────────────────────────────────────
def turn_out(turn: Turn, session_id: str) -> TurnOut:
    keys = turn.audio_keys or ([turn.audio_key] if turn.audio_key else [])
    return TurnOut(
        idx=turn.idx,
        role=turn.role,
        text=turn.text,
        translation_en=turn.translation_en,
        romanization=turn.romanization,
        audio_url=f"/v1/sessions/{session_id}/turns/{turn.idx}/audio" if keys else None,
        audio_sentences=len(keys),
        suggested_replies=turn.suggested_replies or [],
        duration_ms=turn.duration_ms,
        words=turn.stt_words or [],
        stt_provider=turn.stt_provider,
        llm_provider=turn.llm_provider,
        tts_provider=turn.tts_provider,
        created_at=turn.created_at,
    )


def session_state(session: PracticeSession, *, report_ready: bool = False) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "scenario_id": session.scenario_id,
        "language": session.language,
        "level": session.level,
        "status": session.status,
        "turn_budget": {"target": session.target_turns, "used": session.user_turns_used},
        "goals": [GoalState(**g) for g in session.goals_state],
        "options": SessionOptions(**{**SessionOptions().model_dump(), **(session.options or {})}),
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "provider_trace": session.provider_trace or {},
        "report_ready": report_ready,
    }


async def _scenario_doc(db: Db, scenario_id: str) -> dict[str, Any]:
    row = await db.get(Scenario, scenario_id)
    if row is None:
        raise not_found("Scenario")
    return row.yaml


# ── start ───────────────────────────────────────────────────────────────────
@router.post(
    "",
    response_model=StartSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a conversation",
    description=(
        "Returns the character's opening turn immediately. That line is authored in the scenario "
        "pack rather than generated, so starting a session costs no model request and the audio "
        "is usually already cached."
    ),
    responses=problem_responses(401, 404, 422, 429),
)
async def start_session(
    body: StartSessionRequest, user: CurrentUser, db: Db, provider_router: Router
) -> StartSessionResponse:
    await enforce_session_quota(db, user)
    scenario = await _scenario_doc(db, body.scenario_id)

    options = body.options.model_dump()
    prefs = user.prefs
    if prefs is not None:
        # Account preferences are the defaults; the request may override them.
        if "tts_rate" not in body.options.model_fields_set:
            options["tts_rate"] = prefs.tts_rate
        if "tts_tier" not in body.options.model_fields_set:
            options["tts_tier"] = prefs.tts_provider
        options["keep_audio"] = body.options.keep_audio and prefs.keep_audio

    orchestrator = Orchestrator(db, provider_router, user.id)
    session = await orchestrator.start(
        scenario,
        target_turns=body.target_turns or scenario["turn_limits"]["default"],
        options=options,
        tts_tier=options.get("tts_tier", "standard"),
    )
    opening = sorted(session.turns, key=lambda t: t.idx)[0]
    return StartSessionResponse(**session_state(session), ai_turn=turn_out(opening, session.id))


# ── list / detail ───────────────────────────────────────────────────────────
@router.get(
    "",
    response_model=Page[SessionSummary],
    summary="Session history",
    responses=problem_responses(401),
)
async def list_sessions(
    user: CurrentUser,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    language: Annotated[str | None, Query()] = None,
) -> Page[SessionSummary]:
    stmt = (
        select(PracticeSession)
        .where(PracticeSession.user_id == user.id)
        .options(selectinload(PracticeSession.turns))
        .order_by(PracticeSession.started_at.desc())
    )
    if language:
        stmt = stmt.where(PracticeSession.language == language)

    total = await db.scalar(
        select(func.count()).select_from(
            select(PracticeSession.id).where(PracticeSession.user_id == user.id).subquery()
        )
    )
    rows = list(await db.scalars(stmt.offset(offset).limit(limit)))
    scores = dict(
        (
            await db.execute(
                select(Report.session_id, Report.overall).where(
                    Report.session_id.in_([r.id for r in rows] or [""])
                )
            )
        ).all()
    )
    titles: dict[str, dict[str, Any]] = dict(
        (
            await db.execute(
                select(Scenario.id, Scenario.yaml).where(
                    Scenario.id.in_([r.scenario_id for r in rows] or [""])
                )
            )
        ).all()
    )

    items = []
    for row in rows:
        doc = titles.get(row.scenario_id) or {}
        goals = row.goals_state or []
        items.append(
            SessionSummary(
                session_id=row.id,
                scenario_id=row.scenario_id,
                scenario_title=(doc.get("title") or {}).get("en") or row.scenario_id,
                language=row.language,
                level=row.level,
                status=row.status,
                icon=doc.get("icon"),
                started_at=row.started_at,
                ended_at=row.ended_at,
                turns_used=row.user_turns_used,
                target_turns=row.target_turns,
                goals_done=sum(1 for g in goals if g.get("done")),
                goals_total=len(goals),
                overall=scores.get(row.id),
            )
        )
    return Page[SessionSummary](
        items=items,
        total=total,
        next_cursor=str(offset + limit) if offset + limit < (total or 0) else None,
    )


@router.get(
    "/{session_id}",
    response_model=SessionDetail,
    summary="Session state and full transcript",
    responses=problem_responses(401, 403, 404),
)
async def get_session(session_id: str, user: CurrentUser, db: Db) -> SessionDetail:
    orchestrator = Orchestrator(db, get_router(), user.id)
    session = await orchestrator.load(session_id)
    ready = bool(await db.scalar(select(Report.id).where(Report.session_id == session.id)))
    return SessionDetail(
        **session_state(session, report_ready=ready),
        turns=[turn_out(t, session.id) for t in sorted(session.turns, key=lambda t: t.idx)],
    )


# ── the turn endpoint ───────────────────────────────────────────────────────
def _sse(event: SseEvent) -> bytes:
    return f"event: {event.name}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n".encode()


async def _turn_stream(
    session_id: str,
    user_id: str,
    *,
    text: str | None,
    audio: bytes | None,
    content_type: str,
    client_transcript: str | None,
    response_delay_ms: int | None,
    native_lang: str,
) -> AsyncIterator[bytes]:
    """Runs the pipeline on its own DB session and transaction.

    An error after the stream has started cannot change the status code, so it
    is delivered as an `error` event carrying the same problem document the
    non-streaming endpoints would have returned.
    """
    async with get_sessionmaker()() as db:
        try:
            orchestrator = Orchestrator(db, get_router(), user_id)
            session = await orchestrator.load(session_id, for_write=True)
            scenario = await _scenario_doc(db, session.scenario_id)
            async for event in orchestrator.stream_turn(
                session,
                scenario,
                text=text,
                audio=audio,
                content_type=content_type,
                client_transcript=client_transcript,
                response_delay_ms=response_delay_ms,
                tts_tier=(session.options or {}).get("tts_tier", "standard"),
                native_lang=native_lang,
            ):
                yield _sse(event)
            await db.commit()
        except ProblemError as exc:
            await db.rollback()
            yield _sse(SseEvent("error", exc.to_dict()))
        except Exception:
            await db.rollback()
            log.exception("turn pipeline failed")
            yield _sse(
                SseEvent(
                    "error",
                    {
                        "type": "https://talkscene.app/problems/internal",
                        "title": "Turn Failed",
                        "status": 500,
                        "code": "internal",
                        "detail": "Something went wrong on our side. Your turn was not counted.",
                    },
                )
            )


@router.post(
    "/{session_id}/turns",
    summary="Submit a learner turn (text or audio) and stream the reply",
    description=(
        'Send `{"text": ...}` as JSON, or `audio` plus optional `client_transcript` as '
        "`multipart/form-data`. The response is always `text/event-stream` with these events:\n\n"
        "| event | meaning |\n|---|---|\n"
        "| `transcript` | final server-side transcription, with word timings |\n"
        "| `no_speech` | nothing usable was heard; **the turn was not counted** |\n"
        "| `ai_delta` | a chunk of the reply text |\n"
        "| `ai_audio` | a synthesized sentence is ready at `url` |\n"
        "| `ai_replace` | the reply was regenerated (language lock) — replace the text so far |\n"
        "| `meta` | goal progress, translation, romanization, suggested replies |\n"
        "| `turn_state` | turn budget and whether the conversation ended |\n"
        "| `error` | an RFC 9457 problem document; the stream then ends |\n"
        "| `done` | end of stream |"
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-sent event stream",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        **problem_responses(401, 403, 404, 409, 413, 422, 429),
    },
)
async def submit_turn(
    session_id: str,
    request: Request,
    user: CurrentUser,
    db: Db,
    audio: Annotated[UploadFile | None, File(description="webm/opus, wav or mp3.")] = None,
    text: Annotated[str | None, Form()] = None,
    client_transcript: Annotated[
        str | None,
        Form(description="The browser's live transcript. Biases STT and acts as a fallback."),
    ] = None,
    response_delay_ms: Annotated[float | None, Form(ge=0)] = None,
) -> StreamingResponse:
    await throttle(request, user, scope="turn", limit=TURN_LIMIT)

    payload_text = text
    delay = response_delay_ms
    audio_bytes: bytes | None = None
    content_type = "audio/webm"

    if audio is not None:
        audio_bytes = await audio.read()
        if len(audio_bytes) > settings.max_audio_bytes:
            from ..core.errors import audio_too_large

            raise audio_too_large(settings.max_audio_bytes)
        content_type = audio.content_type or content_type
    elif request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = SubmitTurnRequest.model_validate(await request.json())
        except Exception as exc:
            raise unprocessable(f"Invalid JSON body: {exc}") from exc
        payload_text, delay = body.text, body.response_delay_ms

    delay_ms = round(delay) if delay is not None else None

    if not audio_bytes and not (payload_text or "").strip():
        raise unprocessable("Provide either `text` or an `audio` file for this turn.")

    # Validate ownership and state *before* the stream starts, so a rejected
    # turn is an ordinary status code rather than an event inside a 200.
    orchestrator = Orchestrator(db, get_router(), user.id)
    await orchestrator.load(session_id, for_write=True)

    return StreamingResponse(
        _turn_stream(
            session_id,
            user.id,
            text=payload_text,
            audio=audio_bytes,
            content_type=content_type,
            client_transcript=client_transcript,
            response_delay_ms=delay_ms,
            native_lang=user.native_lang,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ── audio ───────────────────────────────────────────────────────────────────
@router.get(
    "/{session_id}/turns/{idx}/audio",
    summary="Fetch or replay a turn's audio",
    description="`?s=N` selects one synthesized sentence; omitted, the first is returned.",
    response_class=Response,
    responses={
        200: {"content": {"audio/mpeg": {}, "audio/wav": {}}, "description": "Audio bytes"},
        **problem_responses(401, 403, 404),
    },
)
async def get_turn_audio(
    session_id: str,
    idx: int,
    user: CurrentUser,
    db: Db,
    s: Annotated[int | None, Query(ge=0, description="Sentence index.")] = None,
) -> Response:
    session = await db.get(PracticeSession, session_id)
    if session is None:
        raise not_found("Session")
    if session.user_id != user.id:
        raise forbidden("This session belongs to another account.")

    turn = await db.scalar(select(Turn).where(Turn.session_id == session_id, Turn.idx == idx))
    if turn is None:
        raise not_found("Turn")

    keys = turn.audio_keys or ([turn.audio_key] if turn.audio_key else [])
    if not keys:
        raise not_found("Audio for this turn")
    if s is not None and s >= len(keys):
        raise not_found(f"Sentence {s} of this turn")

    key = keys[s or 0]
    data = await get_storage().get(key)
    if data is None:
        # Audio is deliberately ephemeral; the transcript outlives it (plan §9).
        raise not_found("Audio (it may have passed its retention window)")

    media = "audio/wav" if key.endswith(".wav") or data[:4] == b"RIFF" else "audio/mpeg"
    return Response(
        data,
        media_type=media,
        headers={
            "Cache-Control": "private, max-age=86400",
            "Content-Disposition": f'inline; filename="{session_id}-{idx}.{media.split("/")[1]}"',
        },
    )


# ── hints (§6.5) ────────────────────────────────────────────────────────────
@router.post(
    "/{session_id}/hint",
    response_model=HintResponse,
    summary="Suggest a reply, translate, explain a word, or slow down the audio",
    description=(
        "`suggest` and `translate` are free: they reuse metadata already returned with the turn, "
        "so they cost no model request. `explain` makes one small cached call."
    ),
    responses=problem_responses(401, 403, 404, 422, 429),
)
async def hint(
    session_id: str,
    body: HintRequest,
    request: Request,
    user: CurrentUser,
    db: Db,
    provider_router: Router,
) -> HintResponse:
    await throttle(request, user, scope="hint", limit=HINT_LIMIT)
    orchestrator = Orchestrator(db, provider_router, user.id)
    session = await orchestrator.load(session_id)
    turns = sorted(session.turns, key=lambda t: t.idx)
    ai_turns = [t for t in turns if t.role == "ai"]
    target_turn = next(
        (t for t in turns if t.idx == body.turn_idx), ai_turns[-1] if ai_turns else None
    )
    limit = settings.quota_hints_per_session

    if body.type == "suggest":
        suggestions = (target_turn.suggested_replies if target_turn else None) or []
        return HintResponse(type="suggest", suggestions=suggestions, hints_limit=limit)

    if body.type == "translate":
        if target_turn is None:
            raise not_found("Turn")
        return HintResponse(
            type="translate",
            translation=target_turn.translation_en,
            romanization=target_turn.romanization,
            hints_limit=limit,
        )

    if body.type == "slow":
        if target_turn is None or not (target_turn.audio_keys or target_turn.audio_key):
            raise not_found("Audio for this turn")
        # The client time-stretches; re-synthesizing at 0.75x would spend quota
        # on a clip we already have.
        return HintResponse(
            type="slow",
            audio_url=f"/v1/sessions/{session_id}/turns/{target_turn.idx}/audio",
            hints_limit=limit,
        )

    target = (body.target or "").strip()
    if not target:
        raise unprocessable("`target` is required for an `explain` hint.")

    from ..core.cache import cache_json, cached_json
    from ..schemas.session import Explanation

    cache_key = f"explain:{session.language}:{session.level}:{target.lower()[:60]}"
    cached = await cached_json(cache_key)
    if cached is None:
        cached = await orchestrator.explain(
            lang=session.language,
            level=session.level,
            target=target,
            context=target_turn.text if target_turn else "",
            native_lang=user.native_lang,
        )
        await cache_json(cache_key, cached, ttl_s=60 * 60 * 24 * 14)

    return HintResponse(
        type="explain",
        billed=True,
        explanation=Explanation(
            term=str(cached.get("term") or target)[:120],
            reading=cached.get("reading") or None,
            meaning=str(cached.get("meaning") or "")[:600],
            part_of_speech=cached.get("part_of_speech") or None,
            example=cached.get("example") or None,
            example_translation=cached.get("example_translation") or None,
            note=cached.get("note") or None,
        ),
        hints_limit=limit,
    )


# ── end ─────────────────────────────────────────────────────────────────────
@router.post(
    "/{session_id}/end",
    response_model=EndSessionResponse,
    summary="End the conversation early and start the analysis",
    responses=problem_responses(401, 403, 404, 409),
)
async def end_session(session_id: str, user: CurrentUser, db: Db) -> EndSessionResponse:
    orchestrator = Orchestrator(db, get_router(), user.id)
    session = await orchestrator.load(session_id)
    await orchestrator.end(session)
    return EndSessionResponse(
        session_id=session.id,
        status=session.status,
        report_url=f"/v1/sessions/{session.id}/report",
    )


@router.post(
    "/{session_id}/abandon",
    response_model=SessionState,
    summary="Abandon a conversation without a report",
    responses=problem_responses(401, 403, 404),
)
async def abandon_session(session_id: str, user: CurrentUser, db: Db) -> SessionState:
    orchestrator = Orchestrator(db, get_router(), user.id)
    session = await orchestrator.load(session_id)
    await orchestrator.abandon(session)
    return SessionState(**session_state(session))

"""Standalone speech utilities (plan §10.1 "Speech utils").

These exist so the SDK, the onboarding microphone test and the evaluation
harness can reach STT and TTS without starting a conversation.  They are the
same router and the same cache as the turn pipeline, so they also serve as the
smoke test for whether a provider key actually works.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from ..core.audio import estimate_duration_s
from ..core.config import settings
from ..core.errors import audio_too_large, not_found, unprocessable
from ..core.ratelimit import Limit
from ..deps import CurrentUser, Db, Router, throttle
from ..engine import speech as speech_service
from ..schemas.common import problem_responses
from ..schemas.session import SttResponse, TtsRequest, WordTiming

router = APIRouter(prefix="/v1", tags=["speech"])

STT_LIMIT = Limit(count=20, per_s=60)
TTS_LIMIT = Limit(count=60, per_s=60)


@router.post(
    "/stt",
    response_model=SttResponse,
    summary="Transcribe an audio clip",
    description=(
        "Pass `client_transcript` to bias recognition toward what the browser already heard — "
        "it is folded into the Whisper prompt, which measurably helps with names and "
        "scenario vocabulary."
    ),
    responses=problem_responses(401, 413, 422, 429, 503),
)
async def transcribe(
    request: Request,
    user: CurrentUser,
    provider_router: Router,
    audio: Annotated[UploadFile, File()],
    lang: Annotated[str, Form(pattern="^(ko|ja|de|en)$")],
    prompt: Annotated[str | None, Form(max_length=400)] = None,
    client_transcript: Annotated[str | None, Form(max_length=600)] = None,
) -> SttResponse:
    await throttle(request, user, scope="stt", limit=STT_LIMIT)
    data = await audio.read()
    if not data:
        raise unprocessable("The audio file is empty.")
    if len(data) > settings.max_audio_bytes:
        raise audio_too_large(settings.max_audio_bytes)
    if (
        estimate_duration_s(data, audio.content_type or "audio/webm")
        > settings.max_audio_seconds * 2
    ):
        raise unprocessable(f"Audio must be under {settings.max_audio_seconds * 2} seconds.")

    result = await provider_router.transcribe(
        data,
        lang=lang,
        prompt=prompt,
        content_type=audio.content_type or "audio/webm",
        client_transcript=client_transcript,
        user_id=user.id,
    )
    return SttResponse(
        text=result.text,
        language=result.language or lang,
        provider=result.provider,
        duration_s=round(result.duration_s, 3),
        no_speech_prob=round(result.no_speech_prob, 4),
        words=[WordTiming(w=w.w, start=w.start, end=w.end, prob=w.prob) for w in result.words],
    )


@router.post(
    "/tts",
    summary="Synthesize speech",
    description=(
        "Cached by provider, voice, rate and text. `X-TTS-Provider` and `X-TTS-Cached` on the "
        "response say which provider served it and whether it was a cache hit — a `mock` "
        "provider means the client should use the browser voice instead."
    ),
    response_class=Response,
    responses={
        200: {"content": {"audio/mpeg": {}, "audio/wav": {}}, "description": "Audio bytes"},
        **problem_responses(401, 422, 429, 503),
    },
)
async def synthesize(
    body: TtsRequest, request: Request, user: CurrentUser, db: Db, provider_router: Router
) -> Response:
    await throttle(request, user, scope="tts", limit=TTS_LIMIT)
    result = await speech_service.synthesize(
        db,
        provider_router,
        body.text,
        lang=body.lang,
        voice=body.voice,
        rate=body.rate,
        user_id=user.id,
        tier="premium",
    )
    if result is None:
        raise not_found("Audio (the premium voice budget for this month is spent)")
    chunk, _key = result
    return Response(
        chunk.data,
        media_type=chunk.content_type,
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-TTS-Provider": chunk.provider,
            "X-TTS-Voice": chunk.voice,
            "X-TTS-Cached": "1" if chunk.cached else "0",
        },
    )

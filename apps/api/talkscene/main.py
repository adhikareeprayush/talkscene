"""FastAPI application assembly.

Startup does the minimum that makes `make api` work from a clean checkout:
create the schema when it is missing, sync the scenario packs, and build the
provider chains.  Everything expensive stays lazy.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .catalog import loader
from .core import tasks
from .core.cache import close_cache, get_cache
from .core.config import settings
from .core.db import create_all, dispose, get_sessionmaker
from .core.errors import install_error_handlers
from .core.logging import request_id_var, setup_logging
from .providers.http import close_client
from .providers.registry import get_router
from .providers.router import UsageEvent
from .routers import admin, auth, catalog, drills, health, learning, me, reports, sessions, speech

log = logging.getLogger("talkscene")

DESCRIPTION = """
Scenario-based language-learning API for **Korean, Japanese, German and English**.

Pick a scenario, hold a 10–15 turn roleplay in voice or text, then get a report on
grammar, vocabulary, fluency and pronunciation.

**Conventions**

* `Authorization: Bearer <JWT>` on everything except the catalog and `/v1/status`.
  `POST /v1/auth/guest` issues an anonymous token immediately.
* Errors are [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) `application/problem+json`
  with a stable `code` field.
* `POST /v1/sessions/{id}/turns` answers with `text/event-stream`; every other
  endpoint is JSON.
* Rate limits appear as `429` with a `Retry-After` header; quota exhaustion as `429`
  with `code: quota-exceeded`.
* Provider degradation is reported, never hidden — poll `GET /v1/status` for the banner.
"""

TAGS = [
    {"name": "auth", "description": "Guest tokens and email accounts."},
    {"name": "me", "description": "Profile, preferences, BYOK keys, export and deletion."},
    {"name": "catalog", "description": "Languages, the scenario library, custom scenarios."},
    {"name": "sessions", "description": "Conversations: start, turns, hints, audio, end."},
    {"name": "feedback", "description": "The end-of-session report."},
    {"name": "drills", "description": "Shadowing drills and pronunciation scoring."},
    {"name": "vocabulary", "description": "Saved words and FSRS flashcard review."},
    {"name": "progress", "description": "Streaks, skill radar and quota meters."},
    {"name": "speech", "description": "Standalone transcription and synthesis."},
    {"name": "admin", "description": "Provider health, usage burn, scenario publishing."},
    {"name": "ops", "description": "Health, readiness, metrics, status banner."},
]


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Correlation id + access log + a `Server-Timing` header for the UI."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-Id"] = request_id
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
        if request.url.path not in ("/healthz", "/readyz", "/metrics"):
            log.info(
                "request",
                extra={
                    "extra_fields": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "duration_ms": round(elapsed_ms, 1),
                    }
                },
            )
        return response


async def _record_usage(event: UsageEvent) -> None:
    """Write one ledger row. Runs on its own session: it must not join, or roll
    back with, the request's transaction."""
    from .models.usage import UsageLedger

    async with get_sessionmaker()() as db:
        db.add(
            UsageLedger(
                user_id=event.user_id,
                capability=event.capability,
                provider=event.provider,
                unit=event.unit,
                amount=event.amount,
                ok=event.ok,
            )
        )
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging(settings.log_level, json_output=settings.env != "dev")
    log.info(
        "starting talkscene",
        extra={"extra_fields": {"version": __version__, "env": settings.env}},
    )

    await create_all()
    async with get_sessionmaker()() as db:
        result = await loader.sync(db)
        await db.commit()
    for error in result.errors:
        log.error("scenario pack rejected", extra={"extra_fields": {"error": error}})

    router = get_router()
    router.set_recorder(_record_usage)
    app.state.provider_router = router
    log.info("cache backend: %s", get_cache().name)

    try:
        yield
    finally:
        # Let an in-flight report finish before the engine goes away.
        await tasks.drain()
        await close_client()
        await close_cache()
        await dispose()
        log.info("talkscene stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="TalkScene API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
        servers=[{"url": settings.public_api_url, "description": settings.env}],
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        # The UI reads these off turn and TTS responses.
        expose_headers=[
            "X-Request-Id",
            "Server-Timing",
            "Retry-After",
            "X-TTS-Provider",
            "X-TTS-Cached",
            "X-TTS-Voice",
        ],
    )
    # SSE must not be buffered by compression, so only JSON bodies are gzipped.
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

    install_error_handlers(app)

    for module in (health, auth, me, catalog, sessions, reports, drills, speech):
        app.include_router(module.router)
    app.include_router(learning.vocab_router)
    app.include_router(learning.srs_router)
    app.include_router(learning.progress_router)
    app.include_router(admin.router)
    return app


app = create_app()

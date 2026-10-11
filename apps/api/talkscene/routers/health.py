"""Liveness, readiness, metrics and the public status banner (plan §16)."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import select, text

from .. import __version__
from ..core.cache import get_cache
from ..core.config import settings
from ..core.db import get_sessionmaker
from ..core.storage import get_storage
from ..deps import Router
from ..models.scenario import Scenario
from ..schemas.learning import SystemStatus

router = APIRouter(tags=["ops"])
_STARTED = time.time()


@router.get("/healthz", summary="Liveness probe", include_in_schema=False)
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "version": __version__, "uptime_s": round(time.time() - _STARTED, 1)}


@router.get("/readyz", summary="Readiness probe", include_in_schema=False)
async def readyz(provider_router: Router) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    ok = True

    try:
        async with get_sessionmaker()() as db:
            await db.execute(text("SELECT 1"))
            count = await db.scalar(select(Scenario.id).limit(1))
        checks["database"] = {"ok": True, "seeded": count is not None}
        ok = ok and count is not None
    except Exception as exc:
        checks["database"] = {"ok": False, "error": str(exc)[:200]}
        ok = False

    cache = get_cache()
    checks["cache"] = {"ok": True, "backend": cache.name}
    if cache.name == "memory":
        # Correct for one worker only; a multi-worker deploy needs Redis for the
        # circuit breaker and the rate limiter to be shared.
        checks["cache"]["warning"] = "in-process cache: run a single worker or configure REDIS_URL"

    checks["storage"] = {"ok": True, "backend": get_storage().name}

    health = await provider_router.health()
    checks["providers"] = {
        "mode": settings.provider_mode,
        "live": sorted({h.provider for h in health if h.configured and h.provider != "mock"}),
        "cooling": sorted({h.provider for h in health if h.state == "cooling"}),
    }

    if settings.is_prod and settings.secret_key.startswith("dev-only"):
        checks["secret_key"] = {"ok": False, "error": "TS_SECRET_KEY is still the dev default"}
        ok = False

    return {"status": "ready" if ok else "degraded", "checks": checks}


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
async def metrics(provider_router: Router) -> Response:
    """Minimal text exposition.

    Deliberately not a full client library: the real pipeline is OpenTelemetry
    (plan §16), and this endpoint exists so a scrape target works out of the box.
    """
    lines = [
        "# HELP talkscene_up Service is up.",
        "# TYPE talkscene_up gauge",
        "talkscene_up 1",
        "# HELP talkscene_uptime_seconds Seconds since process start.",
        "# TYPE talkscene_uptime_seconds gauge",
        f"talkscene_uptime_seconds {time.time() - _STARTED:.1f}",
        "# HELP talkscene_provider_state 1 when a provider is serving, 0 when cooling down.",
        "# TYPE talkscene_provider_state gauge",
    ]
    for item in await provider_router.health():
        if not item.configured:
            continue
        value = 0 if item.state == "cooling" else 1
        lines.append(
            f'talkscene_provider_state{{capability="{item.capability}",'
            f'provider="{item.provider}"}} {value}'
        )
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.get(
    "/v1/status",
    response_model=SystemStatus,
    summary="Public degradation banner",
    description=(
        "What the UI shows in its status banner. Degradation is surfaced rather than hidden: "
        "a learner on mock voices should be told, not left guessing."
    ),
)
async def status(provider_router: Router) -> SystemStatus:
    health = await provider_router.health()
    cooling = [f"{h.capability}:{h.provider}" for h in health if h.state == "cooling"]
    live: dict[str, list[str]] = {}
    for item in health:
        if item.configured and item.provider not in ("mock", "heuristic"):
            live.setdefault(item.capability, []).append(item.provider)

    missing = [cap for cap in ("llm", "stt", "tts") if not live.get(cap)]
    message = ""
    if missing:
        message = (
            "Running on offline placeholder providers for "
            + ", ".join(missing)
            + ". Replies and audio are not real model output."
        )
    elif cooling:
        message = "A provider is rate limited; TalkScene has switched to a backup."

    return SystemStatus(
        status="ok" if not (missing or cooling) else "degraded",
        mode=settings.provider_mode,
        live_providers=live,
        degraded=cooling + [f"{cap}:placeholder" for cap in missing],
        message=message,
    )

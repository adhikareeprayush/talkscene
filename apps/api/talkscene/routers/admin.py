"""Operator endpoints: provider health, usage burn, scenario publishing (plan §11.3 L, §16).

Guarded by `TS_ADMIN_TOKEN` in the `X-Admin-Token` header.  Outside development
an unset token means these endpoints are refused outright rather than left
open, which is the failure mode that matters.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select

from ..catalog import loader
from ..core.config import settings
from ..core.db import get_sessionmaker
from ..core.errors import forbidden, not_found, unauthorized
from ..deps import Db, Router
from ..models.scenario import Scenario
from ..models.session import PracticeSession
from ..models.usage import TtsCache, UsageLedger
from ..schemas.common import Ok, problem_responses
from ..schemas.learning import ProviderHealth

router = APIRouter(prefix="/v1/admin", tags=["admin"])


async def require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    if not settings.admin_token:
        if settings.env == "dev":
            return
        raise forbidden("Admin endpoints are disabled: TS_ADMIN_TOKEN is not set.")
    if x_admin_token != settings.admin_token:
        raise unauthorized("Invalid admin token.")


Admin = Depends(require_admin)


@router.get(
    "/providers/health",
    response_model=list[ProviderHealth],
    summary="Per-provider state, including open circuit breakers",
    dependencies=[Admin],
    responses=problem_responses(401, 403),
)
async def providers_health(provider_router: Router) -> list[ProviderHealth]:
    return [ProviderHealth(**item.as_dict()) for item in await provider_router.health()]


@router.get(
    "/usage",
    summary="Provider burn over a window, for quota alerts",
    dependencies=[Admin],
    responses=problem_responses(401, 403),
)
async def usage_burn(db: Db, hours: Annotated[int, Query(ge=1, le=24 * 31)] = 24) -> dict[str, Any]:
    since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours)
    rows = (
        await db.execute(
            select(
                UsageLedger.capability,
                UsageLedger.provider,
                UsageLedger.unit,
                func.sum(UsageLedger.amount),
                func.count(UsageLedger.id),
            )
            .where(UsageLedger.ts >= since)
            .group_by(UsageLedger.capability, UsageLedger.provider, UsageLedger.unit)
        )
    ).all()

    failures = dict(
        (
            await db.execute(
                select(UsageLedger.provider, func.count(UsageLedger.id))
                .where(UsageLedger.ts >= since, UsageLedger.ok.is_(False))
                .group_by(UsageLedger.provider)
            )
        ).all()
    )

    cache_rows = (
        await db.execute(
            select(func.count(TtsCache.key), func.coalesce(func.sum(TtsCache.hits), 0))
        )
    ).one()
    clips, hits = int(cache_rows[0] or 0), int(cache_rows[1] or 0)

    return {
        "window_hours": hours,
        "by_provider": [
            {
                "capability": capability,
                "provider": provider,
                "unit": unit,
                "amount": round(float(total or 0), 2),
                "calls": int(calls or 0),
                "failures": int(failures.get(provider, 0)),
            }
            for capability, provider, unit, total, calls in rows
        ],
        "tts_cache": {
            "clips": clips,
            "hits": hits,
            # Hit rate against total requests for cached lines; the plan expects
            # 30-50% on scripted content (§4).
            "hit_rate": round(hits / (hits + clips), 3) if (hits + clips) else None,
        },
        "sessions": int(
            await db.scalar(
                select(func.count())
                .select_from(PracticeSession)
                .where(PracticeSession.started_at >= since)
            )
            or 0
        ),
    }


@router.post(
    "/scenarios/sync",
    summary="Re-read the scenario packs from disk",
    description="Idempotent. Bumped `version` values are rewritten; removed packs are unpublished.",
    dependencies=[Admin],
    responses=problem_responses(401, 403),
)
async def sync_scenarios(db: Db) -> dict[str, Any]:
    result = await loader.sync(db)
    return result.as_dict()


@router.get(
    "/scenarios",
    summary="Every scenario, including drafts and private custom ones",
    dependencies=[Admin],
    responses=problem_responses(401, 403),
)
async def list_all_scenarios(
    db: Db,
    published: Annotated[bool | None, Query()] = None,
    language: Annotated[str | None, Query()] = None,
) -> list[dict[str, Any]]:
    stmt = select(Scenario).order_by(Scenario.language, Scenario.level, Scenario.id)
    if published is not None:
        stmt = stmt.where(Scenario.is_published.is_(published))
    if language:
        stmt = stmt.where(Scenario.language == language)
    rows = list(await db.scalars(stmt))
    return [
        {
            "id": r.id,
            "version": r.version,
            "language": r.language,
            "level": r.level,
            "category": r.category,
            "title_en": r.title_en,
            "is_published": r.is_published,
            "author_id": r.author_id,
            "status": r.yaml.get("status", "draft"),
            "reviewed_by": r.yaml.get("reviewed_by"),
        }
        for r in rows
    ]


@router.patch(
    "/scenarios/{scenario_id}/publish",
    response_model=Ok,
    summary="Publish or unpublish a scenario",
    description=(
        "The review gate from the content QA flow (plan §12.2): draft -> reviewed -> published."
    ),
    dependencies=[Admin],
    responses=problem_responses(401, 403, 404),
)
async def set_published(
    scenario_id: str,
    db: Db,
    published: Annotated[bool, Query()] = True,
    reviewed_by: Annotated[str | None, Query(max_length=80)] = None,
) -> Ok:
    row = await db.get(Scenario, scenario_id)
    if row is None:
        raise not_found("Scenario")
    row.is_published = published
    doc = dict(row.yaml)
    doc["status"] = "published" if published else "draft"
    if reviewed_by:
        doc["reviewed_by"] = reviewed_by
    row.yaml = doc
    await db.flush()
    return Ok(detail=f"{scenario_id} is now {'published' if published else 'unpublished'}.")


@router.post(
    "/audio/purge",
    response_model=Ok,
    summary="Delete stored audio past its retention window",
    description=(
        "The retention job from plan §9. Intended for a scheduled worker; exposed here so a "
        "single-VPS deployment can run it from cron."
    ),
    dependencies=[Admin],
    responses=problem_responses(401, 403),
)
async def purge_audio() -> Ok:
    from ..core.storage import get_storage

    removed = await get_storage().purge_older_than(settings.audio_retention_days)
    async with get_sessionmaker()() as db:
        await db.commit()
    return Ok(detail=f"Removed {removed} expired audio object(s).")

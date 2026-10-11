"""Languages, the scenario library, and learner-authored scenarios (plan §10.1)."""

from __future__ import annotations

import base64
import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import func, select

from ..catalog import loader
from ..core.errors import not_found, unprocessable
from ..core.ids import new_id
from ..core.ratelimit import Limit
from ..deps import CurrentUser, Db, OptionalUser, Router, throttle
from ..engine import moderation
from ..engine.meta import parse_json_object
from ..engine.prompts import sanitize_learner_text, scenario_system_prompt
from ..models.report import Report
from ..models.scenario import Scenario
from ..models.session import PracticeSession
from ..providers.base import Msg
from ..schemas.catalog import (
    CustomScenarioRequest,
    CustomScenarioResponse,
    LanguageInfo,
    ScenarioBrief,
    ScenarioCard,
)
from ..schemas.common import Category, Lang, Level, Page, problem_responses

router = APIRouter(prefix="/v1", tags=["catalog"])

CUSTOM_LIMIT = Limit(count=6, per_s=3600)
PAGE_SIZE_MAX = 60


def _encode_cursor(value: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> dict[str, Any]:
    if not cursor:
        return {}
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return value if isinstance(value, dict) else {}
    except Exception:
        raise unprocessable("Cursor is not valid.") from None


@router.get(
    "/languages",
    response_model=list[LanguageInfo],
    summary="Supported languages and their per-language capabilities",
    description=(
        "Capability flags are per language on purpose: the provider matrix is not uniform. "
        "Korean premium voices exist only on Azure, and furigana applies only to Japanese."
    ),
)
async def list_languages(db: Db) -> list[LanguageInfo]:
    rows = await db.execute(
        select(Scenario.language, Scenario.level, func.count(Scenario.id))
        .where(Scenario.is_published.is_(True))
        .group_by(Scenario.language, Scenario.level)
    )
    counts: dict[str, int] = {}
    levels: dict[str, set[str]] = {}
    for language, level, count in rows:
        counts[language] = counts.get(language, 0) + count
        levels.setdefault(language, set()).add(level)

    return [
        LanguageInfo(
            **info,
            scenario_count=counts.get(code, 0),
            levels=[lv for lv in loader.LEVELS if lv in levels.get(code, set())],
        )
        for code, info in loader.LANGUAGE_INFO.items()
    ]


@router.get(
    "/scenarios",
    response_model=Page[ScenarioCard],
    summary="Browse and search the scenario library",
    responses=problem_responses(422),
)
async def list_scenarios(
    db: Db,
    user: OptionalUser,
    lang: Annotated[Lang | None, Query(description="Filter by language.")] = None,
    level: Annotated[Level | None, Query()] = None,
    category: Annotated[Category | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=80, description="Free-text search.")] = None,
    sort: Annotated[str, Query(pattern="^(recommended|newest|shortest)$")] = "recommended",
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=PAGE_SIZE_MAX)] = 24,
) -> Page[ScenarioCard]:
    stmt = select(Scenario).where(Scenario.is_published.is_(True))
    if lang:
        stmt = stmt.where(Scenario.language == lang)
    if level:
        stmt = stmt.where(Scenario.level == level)
    if category:
        stmt = stmt.where(Scenario.category == category)
    if q:
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(Scenario.title_en).like(needle) | func.lower(Scenario.summary).like(needle)
        )
    if tag:
        from ..models.scenario import ScenarioTag

        stmt = stmt.where(
            Scenario.id.in_(select(ScenarioTag.scenario_id).where(ScenarioTag.tag == tag))
        )

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))

    order = {
        "newest": (Scenario.created_at.desc(), Scenario.id),
        "shortest": (Scenario.id,),
        "recommended": (Scenario.level, Scenario.category, Scenario.id),
    }[sort]
    stmt = stmt.order_by(*order)

    state = _decode_cursor(cursor)
    offset = int(state.get("offset", 0))
    rows = list(await db.scalars(stmt.offset(offset).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]

    best: dict[str, int] = {}
    completed: set[str] = set()
    if user is not None and rows:
        ids = [r.id for r in rows]
        result = await db.execute(
            select(PracticeSession.scenario_id, func.max(Report.overall))
            .join(Report, Report.session_id == PracticeSession.id, isouter=True)
            .where(
                PracticeSession.user_id == user.id,
                PracticeSession.scenario_id.in_(ids),
                PracticeSession.status == "completed",
            )
            .group_by(PracticeSession.scenario_id)
        )
        for scenario_id, score in result:
            completed.add(scenario_id)
            if score is not None:
                best[scenario_id] = int(score)

    items = [
        ScenarioCard(
            **loader.card(row.yaml),
            completed=row.id in completed,
            best_score=best.get(row.id),
        )
        for row in rows
    ]
    if sort == "shortest":
        items.sort(key=lambda c: c.estimated_minutes)

    return Page[ScenarioCard](
        items=items,
        next_cursor=_encode_cursor({"offset": offset + limit}) if has_more else None,
        total=total,
    )


@router.get(
    "/scenarios/{scenario_id}",
    response_model=ScenarioBrief,
    summary="Scenario brief shown before the conversation starts",
    responses=problem_responses(404),
)
async def get_scenario(scenario_id: str, db: Db, user: OptionalUser) -> ScenarioBrief:
    row = await db.get(Scenario, scenario_id)
    if row is None or not row.is_published:
        raise not_found("Scenario")

    completed = False
    best: int | None = None
    if user is not None:
        result = await db.execute(
            select(func.max(Report.overall))
            .join(PracticeSession, Report.session_id == PracticeSession.id)
            .where(
                PracticeSession.user_id == user.id,
                PracticeSession.scenario_id == scenario_id,
            )
        )
        value = result.scalar()
        completed = value is not None
        best = int(value) if value is not None else None

    return ScenarioBrief(**loader.brief(row.yaml), completed=completed, best_score=best)


@router.post(
    "/scenarios/custom",
    response_model=CustomScenarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a private scenario from free text",
    description=(
        "Two-stage moderation (plan §6.6): the request is screened before generation, and the "
        "generated document is screened again, because the model's own refusal can be bypassed."
    ),
    responses=problem_responses(401, 422, 429),
)
async def create_custom_scenario(
    body: CustomScenarioRequest,
    request: Request,
    user: CurrentUser,
    db: Db,
    provider_router: Router,
) -> CustomScenarioResponse:
    await throttle(request, user, scope="scenario:custom", limit=CUSTOM_LIMIT)

    prompt = sanitize_learner_text(body.prompt, max_len=moderation.MAX_REQUEST_CHARS)
    screened = moderation.check_scenario_request(prompt)
    if not screened.allowed:
        raise unprocessable(screened.reason, moderation_category=screened.category)

    _, raw = await provider_router.llm_complete(
        [
            Msg("system", scenario_system_prompt(body.language, level=body.level)),
            Msg("user", prompt),
        ],
        user_id=user.id,
        temperature=0.6,
        max_tokens=1200,
        json_mode=True,
    )
    doc = parse_json_object(raw)
    if not doc:
        raise unprocessable("Could not build a scenario from that. Try describing it differently.")

    verdict = moderation.check_generated_scenario(doc)
    if not verdict.allowed:
        raise unprocessable(verdict.reason, moderation_category=verdict.category)

    doc = _normalize_custom(doc, body.language, body.level, user.id)
    # Custom scenarios go through the very same schema as the shipped packs, so
    # a model that drifted cannot produce a document the engine chokes on.
    if errors := loader.validate_doc(doc):
        raise unprocessable(
            "The generated scenario did not validate. Try describing it differently.",
            errors=errors[:4],
        )

    row = Scenario(
        id=doc["id"],
        version=1,
        language=doc["language"],
        level=doc["level"],
        category=doc["category"],
        title_en=doc["title"]["en"],
        summary=doc["summary"],
        yaml=doc,
        # Learner-authored scenarios are private: reachable by id, absent from
        # the public catalog listing.
        is_published=False,
        author_id=user.id,
    )
    db.add(row)
    await db.flush()
    return CustomScenarioResponse(scenario=ScenarioBrief(**loader.brief(doc)), moderation="passed")


def _normalize_custom(doc: dict[str, Any], lang: str, level: str, author_id: str) -> dict[str, Any]:
    """Fill in everything the schema requires that a model tends to omit."""
    slug = new_id("cst").split("_", 1)[1][:10].lower()
    goals = [
        {"id": str(g.get("id") or f"goal_{i}").lower()[:30], "text": str(g.get("text") or "")[:200]}
        for i, g in enumerate(doc.get("goals") or [])
        if str(g.get("text") or "").strip()
    ][:5]
    while len(goals) < 3:
        goals.append({"id": f"goal_{len(goals)}", "text": "Continue the conversation naturally"})

    limits = doc.get("turn_limits") or {}
    turn_limits = {
        "min": int(limits.get("min", 8)),
        "default": int(limits.get("default", 12)),
        "max": int(limits.get("max", 15)),
    }
    turn_limits["default"] = max(
        turn_limits["min"], min(turn_limits["default"], turn_limits["max"])
    )

    persona = doc.get("persona") or {}
    return {
        "id": f"{lang}-custom-{slug}-{level.lower()}",
        "version": 1,
        "language": lang,
        "level": level,
        "category": doc.get("category") if doc.get("category") in loader.CATEGORIES else "social",
        "icon": "✨",
        "title": {"en": str((doc.get("title") or {}).get("en") or "Custom scenario")[:120]},
        "summary": str(doc.get("summary") or "A custom practice conversation.")[:240]
        or "Custom practice.",
        "persona": {
            "name": str(persona.get("name") or "Alex")[:40],
            "role": str(persona.get("role") or "Conversation partner")[:80],
            "style": str(persona.get("style") or "Friendly and patient.")[:200],
        },
        "setting": str(doc.get("setting") or "An everyday setting.")[:300],
        "user_role": str(doc.get("user_role") or "Yourself, practising.")[:300],
        "goals": goals,
        "target_vocab": [str(v)[:60] for v in (doc.get("target_vocab") or [])][:12]
        or ["—", "—", "—"],
        "target_grammar": [str(v)[:80] for v in (doc.get("target_grammar") or [])][:8] or ["—"],
        "opening_line": str(doc.get("opening_line") or "…")[:300],
        "turn_limits": turn_limits,
        "cultural_notes": [str(v)[:300] for v in (doc.get("cultural_notes") or [])][:5],
        "tags": ["custom"],
        "status": "draft",
    }

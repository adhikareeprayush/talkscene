"""Vocabulary, flashcard review, progress and quota meters (plan §11.3 H/I/J)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..core.config import settings
from ..core.errors import conflict, forbidden, not_found
from ..core.ids import vocab_id
from ..deps import Account, CurrentUser, Db, Router, daily_session_limit, sessions_started_today
from ..engine.speech import premium_chars_used_this_month
from ..learning import fsrs
from ..models.report import Report
from ..models.session import PracticeSession
from ..models.usage import UsageLedger
from ..models.vocab import SrsCard, VocabItem
from ..schemas.common import Ok, Page, problem_responses
from ..schemas.learning import (
    DayActivity,
    LanguageProgress,
    Progress,
    QuotaMeter,
    ReviewRequest,
    ReviewResponse,
    SkillRadar,
    Usage,
    VocabIn,
    VocabOut,
)
from ..schemas.learning import SrsCard as SrsCardSchema

vocab_router = APIRouter(prefix="/v1/vocab", tags=["vocabulary"])
srs_router = APIRouter(prefix="/v1/srs", tags=["vocabulary"])
progress_router = APIRouter(prefix="/v1", tags=["progress"])


def _vocab_out(item: VocabItem, card: SrsCard | None = None) -> VocabOut:
    """`card` is passed explicitly where the caller already holds it, so this
    never triggers a lazy load from async code."""
    card = card if card is not None else item.card
    return VocabOut(
        id=item.id,
        language=item.language,
        term=item.term,
        reading=item.reading,
        meaning=item.meaning,
        example=item.example,
        source_session_id=item.source_session_id,
        created_at=item.created_at,
        due_at=card.due_at if card else None,
        state=card.state if card else None,
        reps=card.reps if card else 0,
        lapses=card.lapses if card else 0,
    )


# ── vocabulary ──────────────────────────────────────────────────────────────
@vocab_router.get(
    "",
    response_model=Page[VocabOut],
    summary="Saved words",
    responses=problem_responses(401, 403),
)
async def list_vocab(
    user: Account,
    db: Db,
    language: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=60)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[VocabOut]:
    stmt = (
        select(VocabItem)
        .where(VocabItem.user_id == user.id)
        .options(selectinload(VocabItem.card))
        .order_by(VocabItem.created_at.desc())
    )
    if language:
        stmt = stmt.where(VocabItem.language == language)
    if q:
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(VocabItem.term).like(needle) | func.lower(VocabItem.meaning).like(needle)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list(await db.scalars(stmt.offset(offset).limit(limit)))
    return Page[VocabOut](
        items=[_vocab_out(r) for r in rows],
        total=total,
        next_cursor=str(offset + limit) if offset + limit < (total or 0) else None,
    )


@vocab_router.post(
    "",
    response_model=VocabOut,
    status_code=status.HTTP_201_CREATED,
    summary="Save a word (from tap-to-translate, or by hand)",
    description="Saving a term twice returns the existing card rather than creating a duplicate.",
    responses=problem_responses(401, 403, 422),
)
async def create_vocab(body: VocabIn, user: Account, db: Db) -> VocabOut:
    existing = await db.scalar(
        select(VocabItem)
        .where(
            VocabItem.user_id == user.id,
            VocabItem.language == body.language,
            VocabItem.term == body.term.strip(),
        )
        .options(selectinload(VocabItem.card))
    )
    if existing is not None:
        return _vocab_out(existing)

    # The id is set here so the card can be built and linked before the first
    # flush: assigning a relationship on an already-persistent row would
    # re-load it, which is a lazy load in the middle of async code.
    item = VocabItem(
        id=vocab_id(),
        user_id=user.id,
        language=body.language,
        term=body.term.strip(),
        reading=(body.reading or "").strip() or None,
        meaning=body.meaning.strip(),
        example=(body.example or "").strip() or None,
        source_session_id=body.source_session_id,
    )
    item.card = fsrs.new_card(item.id, user.id)
    db.add(item)
    await db.flush()
    return _vocab_out(item)


@vocab_router.delete(
    "/{vocab_id}",
    response_model=Ok,
    summary="Delete a saved word",
    responses=problem_responses(401, 403, 404),
)
async def delete_vocab(vocab_id: str, user: Account, db: Db) -> Ok:
    item = await db.get(VocabItem, vocab_id)
    if item is None:
        raise not_found("Vocabulary item")
    if item.user_id != user.id:
        raise forbidden("This item belongs to another account.")
    await db.delete(item)
    await db.flush()
    return Ok(detail="Word deleted.")


# ── spaced repetition ───────────────────────────────────────────────────────
@srs_router.get(
    "/due",
    response_model=list[SrsCardSchema],
    summary="Cards due for review",
    description=(
        "Ordered by how overdue each card is. Each card carries `intervals`, which is what every "
        "answer button would schedule, so the UI can show it without a second call."
    ),
    responses=problem_responses(401, 403),
)
async def due_cards(
    user: Account,
    db: Db,
    language: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[SrsCardSchema]:
    now = dt.datetime.now(dt.UTC)
    stmt = (
        select(SrsCard)
        .join(VocabItem, SrsCard.vocab_item_id == VocabItem.id)
        .where(SrsCard.user_id == user.id, SrsCard.due_at <= now)
        .options(selectinload(SrsCard.item))
        .order_by(SrsCard.due_at)
        .limit(limit)
    )
    if language:
        stmt = stmt.where(VocabItem.language == language)
    rows = list(await db.scalars(stmt))
    return [
        SrsCardSchema(
            card_id=card.id,
            vocab=_vocab_out(card.item, card),
            due_at=card.due_at,
            state=card.state,
            reps=card.reps,
            lapses=card.lapses,
            stability=round(card.stability, 3),
            difficulty=round(card.difficulty, 3),
            intervals=fsrs.preview(card, now=now),
        )
        for card in rows
    ]


@srs_router.post(
    "/{card_id}/review",
    response_model=ReviewResponse,
    summary="Answer a flashcard",
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def review_card(card_id: str, body: ReviewRequest, user: Account, db: Db) -> ReviewResponse:
    card = await db.get(SrsCard, card_id)
    if card is None:
        raise not_found("Card")
    if card.user_id != user.id:
        raise forbidden("This card belongs to another account.")

    now = dt.datetime.now(dt.UTC)
    last = card.last_reviewed_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=dt.UTC)
        # Guards a double-tap on the answer button, which would otherwise record
        # two reviews and wreck the card's scheduling.
        if (now - last).total_seconds() < 1.0:
            raise conflict("That card was just reviewed.")

    fsrs.review(card, body.rating, now=now)
    await db.flush()

    remaining = int(
        await db.scalar(
            select(func.count())
            .select_from(SrsCard)
            .where(SrsCard.user_id == user.id, SrsCard.due_at <= now)
        )
        or 0
    )
    return ReviewResponse(
        card_id=card.id,
        due_at=card.due_at,
        scheduled_days=card.scheduled_days,
        state=card.state,
        remaining_due=remaining,
    )


# ── progress ────────────────────────────────────────────────────────────────
@progress_router.get(
    "/progress",
    response_model=Progress,
    summary="Streaks, minutes, skill radar and score trend",
    responses=problem_responses(401),
)
async def progress(
    user: CurrentUser,
    db: Db,
    days: Annotated[int, Query(ge=7, le=180)] = 30,
) -> Progress:
    now = dt.datetime.now(dt.UTC)
    since = now - dt.timedelta(days=days)

    sessions = list(
        await db.scalars(
            select(PracticeSession).where(
                PracticeSession.user_id == user.id,
                PracticeSession.status.in_(("completed", "analyzing")),
            )
        )
    )
    reports = {
        r.session_id: r
        for r in await db.scalars(
            select(Report).where(Report.session_id.in_([s.id for s in sessions] or [""]))
        )
    }

    def minutes(session: PracticeSession) -> float:
        if session.ended_at and session.started_at:
            return max(0.0, (session.ended_at - session.started_at).total_seconds() / 60)
        return 0.0

    today = now.date()
    per_day: dict[dt.date, DayActivity] = {}
    for session in sessions:
        day = session.started_at.date()
        if session.started_at < since:
            continue
        entry = per_day.setdefault(day, DayActivity(date=day, minutes=0.0, sessions=0))
        entry.minutes = round(entry.minutes + minutes(session), 1)
        entry.sessions += 1

    scored = [
        reports[s.id] for s in sorted(sessions, key=lambda s: s.started_at) if s.id in reports
    ]
    radar: SkillRadar | None = None
    if scored:
        recent = scored[-5:]

        def avg(field: str) -> float:
            values = [r.json.get("scores", {}).get(field) for r in recent]
            usable = [float(v) for v in values if isinstance(v, (int, float))]
            return round(sum(usable) / len(usable), 1) if usable else 0.0

        radar = SkillRadar(
            task_completion=avg("task_completion"),
            grammar=avg("grammar"),
            fluency=avg("fluency"),
            pronunciation=avg("pronunciation"),
            vocabulary=avg("vocabulary"),
        )

    words_total = int(
        await db.scalar(
            select(func.count()).select_from(VocabItem).where(VocabItem.user_id == user.id)
        )
        or 0
    )
    cards_due = int(
        await db.scalar(
            select(func.count())
            .select_from(SrsCard)
            .where(SrsCard.user_id == user.id, SrsCard.due_at <= now)
        )
        or 0
    )

    by_language: dict[str, LanguageProgress] = {}
    for session in sessions:
        lang_entry = by_language.setdefault(
            session.language,
            LanguageProgress(
                language=session.language,
                sessions=0,
                minutes=0.0,
                avg_score=None,
                latest_cefr=None,
                words_learned=0,
            ),
        )
        lang_entry.sessions += 1
        lang_entry.minutes = round(lang_entry.minutes + minutes(session), 1)
        report = reports.get(session.id)
        if report is not None:
            scores = [
                reports[s.id].overall
                for s in sessions
                if s.language == session.language and s.id in reports
            ]
            lang_entry.avg_score = round(sum(scores) / len(scores), 1)
            lang_entry.latest_cefr = report.estimated_cefr

    lang_word_counts = dict(
        (
            await db.execute(
                select(VocabItem.language, func.count(VocabItem.id))
                .where(VocabItem.user_id == user.id)
                .group_by(VocabItem.language)
            )
        ).all()
    )
    for code, lang_entry in by_language.items():
        lang_entry.words_learned = int(lang_word_counts.get(code, 0))

    return Progress(
        streak_days=user.streak_days,
        daily_goal_minutes=user.daily_goal_minutes,
        minutes_today=round(
            per_day.get(today, DayActivity(date=today, minutes=0.0, sessions=0)).minutes, 1
        ),
        sessions_total=len(sessions),
        minutes_total=round(sum(minutes(s) for s in sessions), 1),
        words_learned=words_total,
        cards_due=cards_due,
        skill_radar=radar,
        score_trend=[r.overall for r in scored][-20:],
        activity=[per_day[d] for d in sorted(per_day)],
        by_language=sorted(by_language.values(), key=lambda e: -e.sessions),
    )


# ── usage / quota meters ────────────────────────────────────────────────────
@progress_router.get(
    "/usage",
    response_model=Usage,
    summary="Remaining quotas for this account",
    description=(
        "Drives the quota meters in Settings. BYOK accounts report unlimited service quotas, "
        "because their calls are billed to their own provider keys."
    ),
    responses=problem_responses(401),
)
async def usage(user: CurrentUser, db: Db, provider_router: Router) -> Usage:
    byok = bool(user.prefs and user.prefs.byok_keys_encrypted)
    session_limit = daily_session_limit(user)
    sessions_used = await sessions_started_today(db, user.id)
    tts_used = await premium_chars_used_this_month(db, user.id)

    month_start = dt.datetime.now(dt.UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    pron_used = int(
        await db.scalar(
            select(func.coalesce(func.sum(UsageLedger.amount), 0.0)).where(
                UsageLedger.user_id == user.id,
                UsageLedger.capability == "pron",
                UsageLedger.unit == "seconds",
                UsageLedger.ts >= month_start,
            )
        )
        or 0
    )

    meters = [
        QuotaMeter(
            key="sessions",
            label="Conversations today",
            used=sessions_used,
            limit=None if (byok or not session_limit) else session_limit,
            unit="sessions",
            resets="daily",
            exhausted=bool(session_limit and not byok and sessions_used >= session_limit),
        ),
        QuotaMeter(
            key="premium_tts",
            label="Premium voice",
            used=tts_used,
            limit=None if byok else settings.quota_premium_tts_chars_per_month,
            unit="characters",
            resets="monthly",
            exhausted=bool(
                not byok
                and settings.quota_premium_tts_chars_per_month
                and tts_used >= settings.quota_premium_tts_chars_per_month
            ),
        ),
        QuotaMeter(
            key="pronunciation",
            label="Pronunciation scoring",
            used=pron_used,
            limit=None if byok else settings.quota_drill_seconds_per_month,
            unit="seconds",
            resets="monthly",
            exhausted=bool(
                not byok
                and settings.quota_drill_seconds_per_month
                and pron_used >= settings.quota_drill_seconds_per_month
            ),
        ),
    ]
    return Usage(plan=user.plan, meters=meters, byok_active=byok)

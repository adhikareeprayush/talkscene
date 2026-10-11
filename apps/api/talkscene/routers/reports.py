"""The end-of-session report (plan §8, §10.2).

Analysis takes a few seconds, so the first GET starts it in the background and
answers `202 {"status": "analyzing"}`; the client polls and gets `200` with the
report.  `?wait=true` runs it inline instead, which is what the SDK and the
tests use.

A cache lock keyed on the session makes concurrent polls idempotent — without
it, a client polling every second would start five analyses and burn five
model requests on the same conversation.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..core import tasks
from ..core.cache import get_cache
from ..core.db import get_sessionmaker
from ..core.errors import conflict, forbidden, not_found
from ..deps import CurrentUser, Db, Router
from ..engine import feedback
from ..models.report import Report
from ..models.scenario import Scenario
from ..models.session import PracticeSession
from ..providers.registry import get_router
from ..schemas.common import problem_responses
from ..schemas.report import Report as ReportSchema
from ..schemas.report import ReportPending

log = logging.getLogger("talkscene.reports")
router = APIRouter(prefix="/v1/sessions", tags=["feedback"])

LOCK_TTL_S = 180


def _lock_key(session_id: str) -> str:
    return f"report:lock:{session_id}"


async def _generate(session_id: str) -> None:
    """Run the analysis on its own session and transaction."""
    async with get_sessionmaker()() as db:
        try:
            session = await db.scalar(
                select(PracticeSession)
                .where(PracticeSession.id == session_id)
                .options(selectinload(PracticeSession.turns))
            )
            if session is None:
                return
            scenario_row = await db.get(Scenario, session.scenario_id)
            if scenario_row is None:
                return
            await feedback.generate(db, get_router(), session, scenario_row.yaml)
            await db.commit()
        except Exception:
            await db.rollback()
            log.exception(
                "report generation failed", extra={"extra_fields": {"session": session_id}}
            )
        finally:
            await get_cache().delete(_lock_key(session_id))


@router.get(
    "/{session_id}/report",
    # Two success shapes, so the models are declared per status code rather
    # than as one `response_model` that would reject the other.
    response_model=None,
    summary="Get the end-of-session report",
    description=(
        "`202` while the analysis is running, `200` with the report once it is ready. "
        "Pass `wait=true` to block until it is generated instead of polling."
    ),
    responses={
        200: {"description": "The report", "model": ReportSchema},
        202: {"description": "Still analyzing; poll again", "model": ReportPending},
        **problem_responses(401, 403, 404, 409),
    },
)
async def get_report(
    session_id: str,
    user: CurrentUser,
    db: Db,
    provider_router: Router,
    response: Response,
    wait: Annotated[bool, Query(description="Generate inline instead of polling.")] = False,
) -> Any:
    session = await db.scalar(
        select(PracticeSession)
        .where(PracticeSession.id == session_id)
        .options(selectinload(PracticeSession.turns))
    )
    if session is None:
        raise not_found("Session")
    if session.user_id != user.id:
        raise forbidden("This session belongs to another account.")

    existing = await db.scalar(select(Report).where(Report.session_id == session_id))
    if existing is not None:
        return ReportSchema(**existing.json)

    if session.status in ("created", "active"):
        raise conflict("This conversation is still going. End it first to get a report.")
    if session.status == "abandoned":
        raise conflict("This conversation was abandoned, so there is no report.")

    if wait:
        scenario_row = await db.get(Scenario, session.scenario_id)
        if scenario_row is None:
            raise not_found("Scenario")
        report = await feedback.generate(db, provider_router, session, scenario_row.yaml)
        return ReportSchema(**report.json)

    # First poll wins the lock and starts the work; the rest just wait.
    cache = get_cache()
    if await cache.get(_lock_key(session_id)) is None:
        await cache.set(_lock_key(session_id), b"1", ttl_s=LOCK_TTL_S)
        # Tracked so the event loop cannot collect it mid-flight and so
        # shutdown waits for it (see core/tasks.py).
        tasks.spawn(_generate(session_id), name=f"report:{session_id}")

    response.status_code = status.HTTP_202_ACCEPTED
    return ReportPending(session_id=session_id, eta_s=8)

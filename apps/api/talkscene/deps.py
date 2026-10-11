"""FastAPI dependencies: identity, the provider router, and quota guards."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .core.config import settings
from .core.crypto import unseal_map
from .core.db import get_db
from .core.errors import ProblemError, forbidden, quota_exceeded, unauthorized
from .core.ratelimit import Limit, enforce
from .core.security import decode_token
from .models.session import PracticeSession
from .models.user import User, UserPref
from .providers.registry import build_user_router, get_router
from .providers.router import ProviderRouter

Db = Annotated[AsyncSession, Depends(get_db)]


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized("Provide an `Authorization: Bearer <token>` header.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise unauthorized("Bearer token is empty.")
    return token


async def current_user(db: Db, authorization: Annotated[str | None, Header()] = None) -> User:
    payload = decode_token(_bearer(authorization))
    user = await db.get(User, payload["sub"])
    if user is None or user.deleted_at is not None:
        raise unauthorized("Account no longer exists.")
    if user.prefs is None:
        user.prefs = UserPref.defaults(user.id)
        await db.flush()
    await _touch_streak(db, user)
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def optional_user(
    db: Db, authorization: Annotated[str | None, Header()] = None
) -> User | None:
    """For endpoints that work anonymously but personalise when signed in."""
    if not authorization:
        return None
    try:
        return await current_user(db, authorization)
    except ProblemError:
        return None


OptionalUser = Annotated[User | None, Depends(optional_user)]


async def require_account(user: CurrentUser) -> User:
    """Guests may converse, but not own durable data (plan §15)."""
    if user.is_guest:
        raise forbidden("Create an account to use this feature.")
    return user


Account = Annotated[User, Depends(require_account)]


async def _touch_streak(db: AsyncSession, user: User) -> None:
    """Advance the streak on the first authenticated call of a new UTC day."""
    today = dt.datetime.now(dt.UTC).date()
    if user.last_active_on == today:
        return
    if user.last_active_on == today - dt.timedelta(days=1):
        user.streak_days += 1
    elif user.last_active_on != today:
        user.streak_days = 1
    user.last_active_on = today
    await db.flush()


async def provider_router(user: OptionalUser) -> ProviderRouter:
    """The shared router, or a BYOK one when the learner supplied their own keys."""
    if user is not None and user.prefs and user.prefs.byok_keys_encrypted:
        keys = unseal_map(user.prefs.byok_keys_encrypted)
        if keys:
            return build_user_router(keys)
    return get_router()


Router = Annotated[ProviderRouter, Depends(provider_router)]


# ── quota guards (plan §4 mitigation 3, §14.3) ──────────────────────────────
def _tomorrow_utc() -> str:
    now = dt.datetime.now(dt.UTC)
    return (
        now.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
    ).isoformat()


def daily_session_limit(user: User) -> int:
    """0 means unlimited. BYOK learners spend their own quota, so they are too."""
    if user.plan == "byok" or (user.prefs and user.prefs.byok_keys_encrypted):
        return 0
    if user.plan == "plus":
        return settings.quota_plus_sessions_per_day
    return settings.quota_sessions_per_day


async def sessions_started_today(db: AsyncSession, user_id: str) -> int:
    start = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        await db.scalar(
            select(func.count())
            .select_from(PracticeSession)
            .where(
                PracticeSession.user_id == user_id,
                PracticeSession.started_at >= start,
                # An abandoned session before the first reply should not count.
                PracticeSession.status != "abandoned",
            )
        )
        or 0
    )


async def enforce_session_quota(db: AsyncSession, user: User) -> tuple[int, int]:
    limit = daily_session_limit(user)
    used = await sessions_started_today(db, user.id)
    if limit and used >= limit:
        raise quota_exceeded("conversations", limit=limit, resets_at=_tomorrow_utc())
    return used, limit


async def throttle(request: Request, user: User, *, scope: str, limit: Limit) -> None:
    """Per-user limiter, falling back to the client address for anonymous calls."""
    key = user.id if user else (request.client.host if request.client else "anon")
    await enforce(key, limit, scope=scope)

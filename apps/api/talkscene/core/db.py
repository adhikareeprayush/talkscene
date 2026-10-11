"""Async SQLAlchemy engine + session factory.

SQLite is the default so `make api` works with no infrastructure; Postgres is a
URL change.  Relative SQLite paths are resolved against the repo root so the
database does not move when you start the server from a different directory.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from .config import REPO_ROOT, settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def resolve_url(url: str) -> str:
    """Make `sqlite+aiosqlite:///./var/x.db` absolute and ensure its directory exists."""
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return url
    raw = url[len(prefix) :]
    if raw in (":memory:", ""):
        return url
    path = Path(raw)
    if not path.is_absolute():
        path = (REPO_ROOT / raw.lstrip("./")).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{path}"


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = resolve_url(settings.database_url)
        kwargs: dict = {"echo": False, "future": True}
        if url.startswith("sqlite"):
            # A shared in-memory database needs one connection for the whole
            # process, otherwise every session sees an empty schema.
            if ":memory:" in url:
                kwargs |= {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        else:
            kwargs |= {"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True}
        _engine = create_async_engine(url, **kwargs)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one transaction per request, committed on success."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """Create tables directly (dev/test).  Production uses Alembic migrations."""
    from ..models.base import Base

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None

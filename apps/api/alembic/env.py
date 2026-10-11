"""Alembic environment.

Production migrates with Alembic; development and tests use `create_all`
(`talkscene.core.db`).  The URL and the metadata both come from the app, so
there is nothing to keep in sync by hand.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from alembic import context
from talkscene.core.config import settings
from talkscene.core.db import resolve_url
from talkscene.models import Base
from talkscene.models.base import UtcDateTime

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", resolve_url(settings.database_url))
target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Render the app's custom column types without importing app code.

    A migration should keep working after the model module is refactored or
    deleted, so it must not reference `talkscene.*`. Both custom types reduce
    to standard SQLAlchemy constructs at the DDL level: `UtcDateTime` only adds
    Python-side UTC normalisation on top of `TIMESTAMP WITH TIME ZONE`.
    """
    if type_ != "type":
        return False
    if isinstance(obj, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    if isinstance(obj, sa.JSON):
        autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
        return 'sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")'
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER most things in place; batch mode rewrites the
        # table instead, which keeps one migration script valid on both backends.
        render_as_batch=True,
        compare_type=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

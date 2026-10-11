"""Fire-and-forget background work, with a shutdown that waits for it.

Report generation is started by the first poll and finishes after the response
has been sent (`routers/reports.py`).  Two things have to be true for that to
be safe:

* the task must be **referenced**, or the event loop may garbage-collect it
  mid-flight;
* shutdown must **drain** it, or the task keeps running against an engine that
  has already been disposed — which raises inside a task nobody is awaiting.

A real deployment moves this to an ARQ worker (plan §5.1); this keeps the
single-process path honest in the meantime.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger("talkscene.tasks")

_tasks: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task[Any]:
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def pending() -> int:
    return len([t for t in _tasks if not t.done()])


async def drain(timeout_s: float = 20.0) -> None:
    """Let in-flight work finish, then cancel whatever is left."""
    if not _tasks:
        return
    outstanding = list(_tasks)
    log.info("draining %d background task(s)", len(outstanding))
    done, not_done = await asyncio.wait(outstanding, timeout=timeout_s)
    for task in not_done:
        task.cancel()
    if not_done:
        await asyncio.gather(*not_done, return_exceptions=True)
        log.warning("cancelled %d background task(s) at shutdown", len(not_done))
    for task in done:
        if task.cancelled():
            continue
        if (exc := task.exception()) is not None:
            log.error("background task failed: %r", exc)

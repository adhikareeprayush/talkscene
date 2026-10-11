"""Cache + atomic counters, backed by Redis when configured and by an in-process
dict otherwise.

The in-process backend is correct for a single worker only; `GET /readyz`
reports which backend is live so a multi-worker deployment without Redis is
visible rather than silently wrong.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol


class CacheBackend(Protocol):
    name: str

    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ttl_s: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def incr(self, key: str, amount: int = 1, ttl_s: int | None = None) -> int: ...
    async def close(self) -> None: ...


class MemoryCache:
    """TTL dict with an asyncio lock around the read-modify-write paths."""

    name = "memory"

    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, float | None]] = {}
        self._lock = asyncio.Lock()

    def _live(self, key: str) -> bytes | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        value, expires = hit
        if expires is not None and expires <= time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def get(self, key: str) -> bytes | None:
        return self._live(key)

    async def set(self, key: str, value: bytes, ttl_s: int | None = None) -> None:
        self._data[key] = (value, time.monotonic() + ttl_s if ttl_s else None)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def incr(self, key: str, amount: int = 1, ttl_s: int | None = None) -> int:
        async with self._lock:
            current = int(self._live(key) or b"0")
            total = current + amount
            existing = self._data.get(key)
            keep = existing[1] if existing and self._live(key) is not None else None
            self._data[key] = (
                str(total).encode(),
                keep if keep is not None else (time.monotonic() + ttl_s if ttl_s else None),
            )
            return total

    async def close(self) -> None:
        self._data.clear()


class RedisCache:
    name = "redis"

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # imported lazily: optional dependency

        self._r = redis.from_url(url, decode_responses=False)

    async def get(self, key: str) -> bytes | None:
        return await self._r.get(key)

    async def set(self, key: str, value: bytes, ttl_s: int | None = None) -> None:
        await self._r.set(key, value, ex=ttl_s)

    async def delete(self, key: str) -> None:
        await self._r.delete(key)

    async def incr(self, key: str, amount: int = 1, ttl_s: int | None = None) -> int:
        pipe = self._r.pipeline()
        pipe.incrby(key, amount)
        if ttl_s:
            pipe.expire(key, ttl_s, nx=True)
        result = await pipe.execute()
        return int(result[0])

    async def close(self) -> None:
        await self._r.close()


_backend: CacheBackend | None = None


def get_cache() -> CacheBackend:
    global _backend
    if _backend is None:
        from .config import settings

        if settings.redis_url:
            try:
                _backend = RedisCache(settings.redis_url)
            except Exception:  # missing extra, bad URL - degrade, don't crash
                _backend = MemoryCache()
        else:
            _backend = MemoryCache()
    return _backend


def set_cache(backend: CacheBackend) -> None:
    global _backend
    _backend = backend


async def close_cache() -> None:
    global _backend
    if _backend is not None:
        await _backend.close()
    _backend = None


# ── small JSON helpers used across the app ──────────────────────────────────
async def cache_json(key: str, value: Any, ttl_s: int | None = None) -> None:
    import json

    await get_cache().set(key, json.dumps(value, ensure_ascii=False).encode(), ttl_s)


async def cached_json(key: str) -> Any | None:
    import json

    raw = await get_cache().get(key)
    return None if raw is None else json.loads(raw)

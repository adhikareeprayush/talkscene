"""Token buckets.

Two uses, one mechanism (plan §10.4):

* **Vendor mirrors** — a bucket per provider sized to the documented free-tier
  limit (e.g. Groq ~30 RPM).  `acquire()` *waits* for a slot instead of letting
  the vendor return 429, which is the difference between a slow turn and a
  broken one.
* **Caller limits** — per user or per IP, which reject immediately.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .cache import get_cache
from .errors import rate_limited


@dataclass(frozen=True)
class Limit:
    """`count` events per `per_s` seconds."""

    count: int
    per_s: float

    @property
    def interval_s(self) -> float:
        return self.per_s / self.count if self.count else 0.0


class TokenBucket:
    """In-process leaky bucket, used for provider pacing inside one worker."""

    def __init__(self, limit: Limit) -> None:
        self.limit = limit
        self._tokens = float(limit.count)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        self._updated = now
        if self.limit.per_s > 0:
            self._tokens = min(
                float(self.limit.count),
                self._tokens + elapsed * (self.limit.count / self.limit.per_s),
            )

    async def acquire(self, *, timeout_s: float = 10.0) -> bool:
        """Wait for one token.  False means we gave up — caller should fail over."""
        deadline = time.monotonic() + timeout_s
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return True
                wait = max(self.limit.interval_s, 0.02)
            if time.monotonic() + wait > deadline:
                return False
            await asyncio.sleep(wait)

    def try_acquire(self) -> bool:
        self._refill()
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False


class BucketRegistry:
    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}

    def get(self, key: str, limit: Limit) -> TokenBucket:
        bucket = self._buckets.get(key)
        if bucket is None or bucket.limit != limit:
            bucket = TokenBucket(limit)
            self._buckets[key] = bucket
        return bucket


buckets = BucketRegistry()


async def enforce(key: str, limit: Limit, *, scope: str = "request") -> None:
    """Reject-on-exceed limiter for callers.  Shared across workers via the cache."""
    window = int(limit.per_s)
    slot = int(time.time() // window) if window else 0
    counter_key = f"rl:{scope}:{key}:{slot}"
    used = await get_cache().incr(counter_key, 1, ttl_s=window + 1)
    if used > limit.count:
        remaining_window = window - int(time.time() % window) if window else 1
        raise rate_limited(max(remaining_window, 1))


# Documented free-tier shapes, kept here so updating a vendor limit is one edit.
# Verify in the vendor console - these rotate (plan §3, §18).
PROVIDER_LIMITS: dict[str, Limit] = {
    "llm:groq": Limit(count=28, per_s=60),  # documented ~30 RPM, 2 held back
    "llm:gemini": Limit(count=14, per_s=60),
    "llm:xai": Limit(count=60, per_s=60),
    "llm:ollama": Limit(count=120, per_s=60),
    "stt:groq_whisper": Limit(count=18, per_s=60),  # documented ~20 RPM
    "stt:deepgram": Limit(count=100, per_s=60),
    "stt:azure": Limit(count=20, per_s=60),
    "tts:azure": Limit(count=60, per_s=60),
    "tts:deepgram": Limit(count=60, per_s=60),
    "pron:azure": Limit(count=20, per_s=60),
    # The offline adapters are local code with no vendor behind them, so there
    # is nothing to pace. Without these they would inherit the default bucket
    # and throttle development and tests for no reason.
    "llm:mock": Limit(count=100_000, per_s=60),
    "stt:mock": Limit(count=100_000, per_s=60),
    "tts:mock": Limit(count=100_000, per_s=60),
    "pron:heuristic": Limit(count=100_000, per_s=60),
}


def provider_limit(capability: str, provider: str) -> Limit:
    return PROVIDER_LIMITS.get(f"{capability}:{provider}", Limit(count=60, per_s=60))

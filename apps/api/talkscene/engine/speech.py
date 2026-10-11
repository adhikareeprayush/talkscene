"""TTS with caching, and the premium-voice quota gate (plan §4, §7.4, §14.3).

Scripted lines — scenario openers, drill sentences, corrected examples — repeat
across every learner, so caching them is the single biggest lever on the Azure
0.5M-character monthly allowance.  The cache key covers provider, voice, rate
and text, so changing any of them is a miss rather than a wrong clip.

The premium tier degrades instead of failing: when the monthly character budget
is spent, synthesis returns `None` and the client speaks the line with the
browser's own `speechSynthesis` (plan §14.3).
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.storage import get_storage, tts_cache_key
from ..models.usage import TtsCache, UsageLedger
from ..providers.base import AudioChunk
from ..providers.router import ProviderRouter

log = logging.getLogger("talkscene.speech")


async def premium_chars_used_this_month(db: AsyncSession, user_id: str | None) -> int:
    start = dt.datetime.now(dt.UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    stmt = select(func.coalesce(func.sum(UsageLedger.amount), 0.0)).where(
        UsageLedger.capability == "tts",
        UsageLedger.unit == "chars",
        UsageLedger.provider != "mock",
        UsageLedger.ts >= start,
    )
    if user_id:
        stmt = stmt.where(UsageLedger.user_id == user_id)
    return int((await db.scalar(stmt)) or 0)


async def premium_allowed(db: AsyncSession, user_id: str | None, *, chars: int) -> bool:
    budget = settings.quota_premium_tts_chars_per_month
    if budget <= 0:
        return True
    return await premium_chars_used_this_month(db, user_id) + chars <= budget


async def synthesize(
    db: AsyncSession,
    router: ProviderRouter,
    text: str,
    *,
    lang: str,
    voice: str | None = None,
    rate: float = 1.0,
    user_id: str | None = None,
    tier: str = "premium",
) -> tuple[AudioChunk, str] | None:
    """Synthesize one sentence, cache-first.

    Returns `(chunk, storage_key)`, or `None` when the client should speak the
    line itself — either because the learner chose the standard (browser) voice
    or because the premium monthly budget is exhausted.
    """
    text = text.strip()
    if not text:
        return None

    if tier == "standard":
        return None

    chain = router.tts_chain(lang)
    if not chain:
        return None
    # Cache against the provider we would actually reach, so a failover does not
    # serve audio from a voice the learner is not getting any more.
    intended = chain[0]
    chosen_voice = intended.voice_for(lang, voice)
    key = tts_cache_key(intended.name, chosen_voice, rate, text)

    storage = get_storage()
    row = await db.get(TtsCache, key)
    if row is not None:
        data = await storage.get(key)
        if data:
            row.hits += 1
            return (
                AudioChunk(
                    data=data,
                    content_type=row.content_type,
                    voice=row.voice,
                    provider=row.provider,
                    chars=row.chars,
                    cached=True,
                ),
                key,
            )
        # Row without a blob: the object was purged by retention. Drop and refill.
        await db.delete(row)

    if intended.name != "mock" and not await premium_allowed(db, user_id, chars=len(text) * 2):
        log.info("premium tts budget exhausted; deferring to browser voice")
        return None

    chunk = await router.synthesize(text, lang=lang, voice=voice, rate=rate, user_id=user_id)
    await storage.put(key, chunk.data, chunk.content_type)
    db.add(
        TtsCache(
            key=key,
            provider=chunk.provider,
            voice=chunk.voice,
            language=lang,
            chars=chunk.chars or len(text),
            content_type=chunk.content_type,
        )
    )
    return chunk, key


async def prewarm(
    db: AsyncSession,
    router: ProviderRouter,
    lines: list[str],
    *,
    lang: str,
    voice: str | None = None,
) -> int:
    """Pre-synthesize scripted lines (openers, drill sentences). Returns new clips."""
    made = 0
    for line in lines:
        try:
            result = await synthesize(db, router, line, lang=lang, voice=voice)
        except Exception:  # prewarming is best-effort and must never fail a request
            log.warning("tts prewarm failed", exc_info=True)
            continue
        if result and not result[0].cached:
            made += 1
    return made

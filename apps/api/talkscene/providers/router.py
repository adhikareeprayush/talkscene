"""Provider router: ordering, pacing, failover, health and accounting.

Four behaviours, applied uniformly to every capability (plan §10.4):

1. **Order** comes from config — a per-language chain for TTS, a flat chain for
   the rest — and always ends in a provider that cannot fail.
2. **Pace**: a token bucket per provider mirrors the vendor's documented limit,
   so a burst *waits* instead of collecting a 429.
3. **Trip**: a 429 or 5xx opens a circuit for that provider (honouring
   `Retry-After`) and the next one takes over.  The breaker lives in the shared
   cache, so with Redis every worker learns about it at once.
4. **Account**: every attempt is reported to the usage ledger, successes and
   failures alike, which is what the quota meters and the provider-health view
   read.

Streaming failover has one honest limitation: a provider is only committed to
once its **first token** arrives.  Before that, errors fail over silently;
after it, the stream is already in front of the learner, so a mid-stream
failure ends that turn rather than restarting it under a different voice.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..core.cache import get_cache
from ..core.ratelimit import buckets, provider_limit
from .base import (
    AudioChunk,
    Capability,
    LLMProvider,
    Msg,
    PAResult,
    PronunciationProvider,
    ProviderError,
    ProviderRateLimited,
    STTProvider,
    STTResult,
    TTSProvider,
)

log = logging.getLogger("talkscene.router")

COOLDOWN_DEFAULT_S = 30
COOLDOWN_MAX_S = 900


@dataclass(slots=True)
class UsageEvent:
    capability: Capability
    provider: str
    unit: str  # requests | tokens | chars | seconds
    amount: float
    ok: bool = True
    user_id: str | None = None


Recorder = Callable[[UsageEvent], Awaitable[None]]


@dataclass(slots=True)
class ProviderHealth:
    capability: str
    provider: str
    configured: bool
    state: str  # ok | cooling | unconfigured
    cooling_until: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "provider": self.provider,
            "configured": self.configured,
            "state": self.state,
            "cooling_until": self.cooling_until,
        }


class CircuitBreaker:
    """Cooldown markers in the shared cache, keyed `cb:<capability>:<provider>`."""

    @staticmethod
    def _key(capability: str, provider: str) -> str:
        return f"cb:{capability}:{provider}"

    async def cooling_until(self, capability: str, provider: str) -> float | None:
        raw = await get_cache().get(self._key(capability, provider))
        if raw is None:
            return None
        try:
            until = float(raw)
        except ValueError:
            return None
        return until if until > time.time() else None

    async def is_open(self, capability: str, provider: str) -> bool:
        return await self.cooling_until(capability, provider) is not None

    async def trip(self, capability: str, provider: str, seconds: float) -> None:
        seconds = max(1.0, min(float(seconds), COOLDOWN_MAX_S))
        until = time.time() + seconds
        await get_cache().set(
            self._key(capability, provider), str(until).encode(), ttl_s=int(seconds) + 1
        )
        log.warning(
            "circuit open",
            extra={
                "extra_fields": {"capability": capability, "provider": provider, "for_s": seconds}
            },
        )

    async def reset(self, capability: str, provider: str) -> None:
        await get_cache().delete(self._key(capability, provider))


class ProviderRouter:
    def __init__(
        self,
        *,
        llm: list[LLMProvider],
        stt: list[STTProvider],
        tts: dict[str, list[TTSProvider]],
        pron: list[PronunciationProvider],
        recorder: Recorder | None = None,
    ) -> None:
        self.llm = llm
        self.stt = stt
        self.tts = tts  # keyed by language
        self.pron = pron
        self.breaker = CircuitBreaker()
        self._recorder = recorder

    def set_recorder(self, recorder: Recorder | None) -> None:
        self._recorder = recorder

    # ── internals ───────────────────────────────────────────────────────────
    async def _record(self, event: UsageEvent) -> None:
        if self._recorder is None:
            return
        try:
            await self._recorder(event)
        except Exception:  # accounting must never break a learner's turn
            log.exception("usage recording failed")

    async def _usable(self, capability: Capability, providers: list[Any]) -> list[Any]:
        """Configured providers whose circuit is closed, in configured order."""
        out = []
        for p in providers:
            if not p.configured:
                continue
            if await self.breaker.is_open(capability, p.name):
                continue
            out.append(p)
        # Everything cooling down at once: fall back to the last resort anyway
        # rather than failing the turn (plan §14.3 - degrade, don't block).
        if not out:
            out = [p for p in providers if p.configured and p.name in ("mock", "heuristic")]
        return out

    async def _pace(self, capability: Capability, provider: Any) -> bool:
        limit = provider_limit(capability, provider.name)
        bucket = buckets.get(f"{capability}:{provider.name}", limit)
        return await bucket.acquire(timeout_s=8.0)

    async def _handle_failure(
        self, capability: Capability, provider: Any, exc: ProviderError, user_id: str | None
    ) -> None:
        cooldown = exc.retry_after_s if isinstance(exc, ProviderRateLimited) else COOLDOWN_DEFAULT_S
        await self.breaker.trip(capability, provider.name, cooldown)
        await self._record(
            UsageEvent(capability, provider.name, "requests", 1, ok=False, user_id=user_id)
        )
        log.warning(
            "provider failed over",
            extra={
                "extra_fields": {
                    "capability": capability,
                    "provider": provider.name,
                    "detail": exc.detail,
                }
            },
        )

    # ── LLM ─────────────────────────────────────────────────────────────────
    async def llm_stream(
        self,
        messages: list[Msg],
        *,
        user_id: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 320,
        json_mode: bool = False,
    ) -> AsyncIterator[tuple[str, str]]:
        """Yields `(provider_name, text_delta)`.  The first tuple names the winner."""
        tried: list[str] = []
        for provider in await self._usable("llm", self.llm):
            tried.append(provider.name)
            if not await self._pace("llm", provider):
                await self.breaker.trip("llm", provider.name, 5)
                continue

            first = True
            produced = 0
            try:
                stream = provider.chat_stream(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
                async for delta in stream:
                    if first:
                        first = False
                        await self.breaker.reset("llm", provider.name)
                    produced += len(delta)
                    yield provider.name, delta
            except ProviderError as exc:
                if first:
                    await self._handle_failure("llm", provider, exc, user_id)
                    continue  # nothing shown to the learner yet: fail over
                # Already streaming: end this turn, but still trip the breaker so
                # the next turn starts on a healthy provider.
                await self._handle_failure("llm", provider, exc, user_id)
                return

            if produced == 0 and first:
                # Empty stream counts as a failure, not as a silent AI.
                await self.breaker.trip("llm", provider.name, 10)
                continue

            prompt_chars = sum(len(m.content) for m in messages)
            await self._record(UsageEvent("llm", provider.name, "requests", 1, user_id=user_id))
            await self._record(
                UsageEvent(
                    "llm",
                    provider.name,
                    "tokens",
                    # ~4 chars per token; good enough for a quota meter, and the
                    # ledger records the estimate as such.
                    round((prompt_chars + produced) / 4),
                    user_id=user_id,
                )
            )
            return

        from ..core.errors import provider_unavailable

        raise provider_unavailable("LLM", tried)

    async def llm_complete(
        self,
        messages: list[Msg],
        *,
        user_id: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1200,
        json_mode: bool = False,
    ) -> tuple[str, str]:
        """Collect a whole response. Used for feedback, hints and scenario drafts."""
        provider_name = ""
        parts: list[str] = []
        async for name, delta in self.llm_stream(
            messages,
            user_id=user_id,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        ):
            provider_name = name
            parts.append(delta)
        return provider_name, "".join(parts)

    # ── STT ─────────────────────────────────────────────────────────────────
    async def transcribe(
        self,
        audio: bytes,
        *,
        lang: str,
        prompt: str | None = None,
        content_type: str = "audio/webm",
        client_transcript: str | None = None,
        user_id: str | None = None,
    ) -> STTResult:
        tried: list[str] = []
        for provider in await self._usable("stt", self.stt):
            tried.append(provider.name)
            if not await self._pace("stt", provider):
                await self.breaker.trip("stt", provider.name, 5)
                continue
            try:
                result = await provider.transcribe(
                    audio,
                    lang=lang,
                    prompt=prompt,
                    content_type=content_type,
                    client_transcript=client_transcript,
                )
            except ProviderError as exc:
                await self._handle_failure("stt", provider, exc, user_id)
                continue
            await self.breaker.reset("stt", provider.name)
            await self._record(UsageEvent("stt", provider.name, "requests", 1, user_id=user_id))
            await self._record(
                UsageEvent("stt", provider.name, "seconds", result.duration_s, user_id=user_id)
            )
            return result

        from ..core.errors import provider_unavailable

        raise provider_unavailable("speech-to-text", tried)

    # ── TTS ─────────────────────────────────────────────────────────────────
    def tts_chain(self, lang: str) -> list[TTSProvider]:
        return self.tts.get(lang) or self.tts.get("en") or []

    async def synthesize(
        self,
        text: str,
        *,
        lang: str,
        voice: str | None = None,
        rate: float = 1.0,
        user_id: str | None = None,
    ) -> AudioChunk:
        tried: list[str] = []
        for provider in await self._usable("tts", self.tts_chain(lang)):
            tried.append(provider.name)
            if not await self._pace("tts", provider):
                await self.breaker.trip("tts", provider.name, 5)
                continue
            try:
                chunk = await provider.synthesize(text, lang=lang, voice=voice, rate=rate)
            except ProviderError as exc:
                await self._handle_failure("tts", provider, exc, user_id)
                continue
            await self.breaker.reset("tts", provider.name)
            await self._record(UsageEvent("tts", provider.name, "requests", 1, user_id=user_id))
            await self._record(
                UsageEvent("tts", provider.name, "chars", chunk.chars or len(text), user_id=user_id)
            )
            return chunk

        from ..core.errors import provider_unavailable

        raise provider_unavailable("text-to-speech", tried)

    # ── pronunciation ───────────────────────────────────────────────────────
    async def assess(
        self,
        audio: bytes,
        *,
        lang: str,
        reference_text: str,
        content_type: str = "audio/webm",
        user_id: str | None = None,
        duration_s: float = 0.0,
    ) -> PAResult:
        tried: list[str] = []
        for provider in await self._usable("pron", self.pron):
            tried.append(provider.name)
            if not await self._pace("pron", provider):
                continue
            try:
                result = await provider.assess(
                    audio, lang=lang, reference_text=reference_text, content_type=content_type
                )
            except ProviderError as exc:
                await self._handle_failure("pron", provider, exc, user_id)
                continue
            await self.breaker.reset("pron", provider.name)
            await self._record(UsageEvent("pron", provider.name, "requests", 1, user_id=user_id))
            if duration_s:
                await self._record(
                    UsageEvent("pron", provider.name, "seconds", duration_s, user_id=user_id)
                )
            return result

        from ..core.errors import provider_unavailable

        raise provider_unavailable("pronunciation assessment", tried)

    # ── health ──────────────────────────────────────────────────────────────
    async def health(self) -> list[ProviderHealth]:
        out: list[ProviderHealth] = []
        groups: list[tuple[Capability, list[Any]]] = [
            ("llm", self.llm),
            ("stt", self.stt),
            ("pron", self.pron),
        ]
        seen_tts: dict[str, Any] = {}
        for chain in self.tts.values():
            for p in chain:
                seen_tts[p.name] = p
        groups.append(("tts", list(seen_tts.values())))

        for capability, providers in groups:
            for p in providers:
                until = await self.breaker.cooling_until(capability, p.name)
                state = "unconfigured" if not p.configured else "cooling" if until else "ok"
                out.append(ProviderHealth(capability, p.name, p.configured, state, until))
        return out

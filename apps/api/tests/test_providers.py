"""Router behaviour: ordering, failover, the circuit breaker, accounting.

These are the guarantees ADR 0002 makes, so they are tested against fake
adapters rather than through the API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from talkscene.core import cache as cache_mod
from talkscene.core.config import Settings
from talkscene.providers.base import (
    AudioChunk,
    Msg,
    ProviderRateLimited,
    ProviderUnavailable,
    STTResult,
    Word,
)
from talkscene.providers.registry import LiveProviderMissing, build_router, build_tts_chains
from talkscene.providers.router import ProviderRouter, UsageEvent
from talkscene.providers.tts.deepgram import DeepgramTTS


class FakeLLM:
    def __init__(
        self, name: str, *, fail: Exception | None = None, text: str = "ok", configured: bool = True
    ) -> None:
        self.name = name
        self.model = f"{name}-model"
        self._fail = fail
        self._text = text
        self._configured = configured
        self.calls = 0

    @property
    def configured(self) -> bool:
        return self._configured

    async def chat_stream(self, messages, **kwargs) -> AsyncIterator[str]:
        self.calls += 1
        if self._fail is not None:
            raise self._fail
        for piece in self._text.split():
            yield piece + " "


class MidStreamFailLLM:
    name = "midstream"
    model = "midstream-model"
    configured = True

    async def chat_stream(self, messages, **kwargs) -> AsyncIterator[str]:
        yield "first "
        raise ProviderUnavailable(self.name, "connection reset")


class FakeSTT:
    def __init__(self, name: str, *, fail: Exception | None = None) -> None:
        self.name = name
        self._fail = fail
        self.calls = 0

    configured = True

    async def transcribe(self, audio: bytes, **kwargs) -> STTResult:
        self.calls += 1
        if self._fail is not None:
            raise self._fail
        return STTResult(
            text="hello", words=[Word("hello", 0, 0.4, 0.9)], duration_s=0.4, provider=self.name
        )


class FakeTTS:
    def __init__(self, name: str, *, fail: Exception | None = None) -> None:
        self.name = name
        self._fail = fail

    configured = True

    def voice_for(self, lang: str, preferred: str | None = None) -> str:
        return preferred or f"{self.name}-{lang}"

    async def synthesize(self, text: str, **kwargs) -> AudioChunk:
        if self._fail is not None:
            raise self._fail
        return AudioChunk(data=b"audio", provider=self.name, chars=len(text))


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    """The circuit breaker lives in the cache, so each test starts clean."""
    cache_mod.set_cache(cache_mod.MemoryCache())


def make_router(**kwargs) -> tuple[ProviderRouter, list[UsageEvent]]:
    ledger: list[UsageEvent] = []

    async def record(event: UsageEvent) -> None:
        ledger.append(event)

    router = ProviderRouter(
        llm=kwargs.get("llm", []),
        stt=kwargs.get("stt", []),
        tts=kwargs.get("tts", {}),
        pron=kwargs.get("pron", []),
        recorder=record,
    )
    return router, ledger


async def collect(stream) -> tuple[str, str]:
    provider, parts = "", []
    async for name, delta in stream:
        provider = name
        parts.append(delta)
    return provider, "".join(parts)


# ── LLM failover ────────────────────────────────────────────────────────────
async def test_a_rate_limited_provider_hands_over_to_the_next() -> None:
    primary = FakeLLM("primary", fail=ProviderRateLimited("primary", 45))
    backup = FakeLLM("backup", text="backup reply")
    router, ledger = make_router(llm=[primary, backup])

    provider, text = await collect(router.llm_stream([Msg("user", "hi")]))
    assert provider == "backup"
    assert text.strip() == "backup reply"

    # The breaker is open for the primary, honouring its Retry-After.
    assert await router.breaker.is_open("llm", "primary") is True
    assert any(e.provider == "primary" and e.ok is False for e in ledger)
    assert any(e.provider == "backup" and e.ok is True for e in ledger)


async def test_an_open_breaker_is_skipped_without_another_attempt() -> None:
    primary = FakeLLM("primary", fail=ProviderUnavailable("primary", "500"))
    backup = FakeLLM("backup")
    router, _ = make_router(llm=[primary, backup])

    await collect(router.llm_stream([Msg("user", "hi")]))
    assert primary.calls == 1
    await collect(router.llm_stream([Msg("user", "hi")]))
    assert primary.calls == 1, "a cooling provider must not be retried on every turn"
    assert backup.calls == 2


async def test_a_failure_after_the_first_token_ends_the_turn_rather_than_restarting_it() -> None:
    """Honest limitation: the learner has already seen text, so we do not
    silently replay the turn under a different provider."""
    router, _ = make_router(llm=[MidStreamFailLLM(), FakeLLM("backup", text="different reply")])
    provider, text = await collect(router.llm_stream([Msg("user", "hi")]))
    assert provider == "midstream"
    assert text == "first "
    # The breaker still trips, so the next turn starts on a healthy provider.
    assert await router.breaker.is_open("llm", "midstream") is True


async def test_an_empty_stream_counts_as_a_failure() -> None:
    silent = FakeLLM("silent", text="")
    backup = FakeLLM("backup", text="real reply")
    router, _ = make_router(llm=[silent, backup])
    provider, text = await collect(router.llm_stream([Msg("user", "hi")]))
    assert provider == "backup"
    assert text.strip() == "real reply"


async def test_unconfigured_providers_are_never_called() -> None:
    unconfigured = FakeLLM("nokey", configured=False)
    live = FakeLLM("live")
    router, _ = make_router(llm=[unconfigured, live])
    await collect(router.llm_stream([Msg("user", "hi")]))
    assert unconfigured.calls == 0
    assert live.calls == 1


async def test_every_provider_failing_raises_a_problem_naming_what_was_tried() -> None:
    from talkscene.core.errors import ProblemError

    router, _ = make_router(
        llm=[
            FakeLLM("a", fail=ProviderUnavailable("a", "down")),
            FakeLLM("b", fail=ProviderUnavailable("b", "down")),
        ]
    )
    with pytest.raises(ProblemError) as exc:
        await collect(router.llm_stream([Msg("user", "hi")]))
    assert exc.value.status == 503
    assert exc.value.code == "provider-unavailable"
    assert exc.value.extra["tried"] == ["a", "b"]


# ── STT and TTS ─────────────────────────────────────────────────────────────
async def test_stt_failover_records_audio_seconds() -> None:
    router, ledger = make_router(
        stt=[FakeSTT("first", fail=ProviderRateLimited("first", 10)), FakeSTT("second")]
    )
    result = await router.transcribe(b"audio", lang="ko")
    assert result.provider == "second"
    assert any(e.unit == "seconds" and e.amount == pytest.approx(0.4) for e in ledger)


async def test_tts_routing_is_per_language() -> None:
    azure = FakeTTS("azure")
    deepgram = FakeTTS("deepgram")
    router, _ = make_router(tts={"ko": [azure], "en": [deepgram, azure]})

    assert (await router.synthesize("안녕", lang="ko")).provider == "azure"
    assert (await router.synthesize("hello", lang="en")).provider == "deepgram"


async def test_an_unknown_language_falls_back_to_the_english_chain() -> None:
    router, _ = make_router(tts={"en": [FakeTTS("azure")]})
    assert (await router.synthesize("hola", lang="es")).provider == "azure"


async def test_deepgram_refuses_korean_instead_of_synthesizing_the_wrong_language() -> None:
    """Aura-2 has no Korean voice, and silently serving another one would be
    worse than failing over (plan §3.3)."""
    adapter = DeepgramTTS("fake-key", "aura-2-thalia-en")
    assert adapter.supports("ko") is False
    assert adapter.supports("ja") is True
    with pytest.raises(ProviderUnavailable):
        await adapter.synthesize("안녕하세요", lang="ko")


def test_the_korean_tts_chain_never_contains_deepgram() -> None:
    settings = Settings(
        TS_PROVIDER_MODE="auto",
        AZURE_SPEECH_KEY="fake",
        AZURE_SPEECH_REGION="eastus",
        DEEPGRAM_API_KEY="fake",
    )
    chains = build_tts_chains(settings)
    assert "deepgram" not in [p.name for p in chains["ko"]]
    assert "deepgram" in [p.name for p in chains["ja"]]
    # Every chain still ends in something that cannot fail.
    assert all(chain[-1].name == "mock" for chain in chains.values())


# ── registry wiring ─────────────────────────────────────────────────────────
def test_an_empty_environment_still_produces_a_working_stack() -> None:
    """ADR 0002: an empty `.env` must still boot a complete, working stack —
    and must not probe a local model nobody asked for."""
    router = build_router(Settings(TS_PROVIDER_MODE="auto", GROQ_API_KEY=""))
    assert [p.name for p in router.llm] == ["mock"]
    assert [p.name for p in router.stt] == ["mock"]
    assert router.pron[-1].name == "heuristic"


def test_a_local_model_is_opt_in() -> None:
    router = build_router(Settings(TS_PROVIDER_MODE="auto", LLM_PROVIDERS="ollama"))
    assert [p.name for p in router.llm] == ["ollama", "mock"]


def test_live_mode_refuses_to_start_on_mocks() -> None:
    with pytest.raises(LiveProviderMissing) as exc:
        build_router(Settings(TS_PROVIDER_MODE="live", GROQ_API_KEY=""))
    assert "GROQ_API_KEY" in str(exc.value)


def test_live_mode_accepts_a_configured_provider() -> None:
    router = build_router(
        Settings(
            TS_PROVIDER_MODE="live",
            GROQ_API_KEY="gsk_fake",
            LLM_PROVIDERS="groq",
            STT_PROVIDERS="groq_whisper",
        )
    )
    assert [p.name for p in router.llm] == ["groq", "mock"]
    assert [p.name for p in router.stt] == ["groq_whisper", "mock"]


def test_model_names_come_from_configuration_not_code() -> None:
    settings = Settings(
        TS_PROVIDER_MODE="auto", GROQ_API_KEY="gsk_fake", LLM_GROQ_MODEL="some-future-model"
    )
    router = build_router(settings)
    assert router.llm[0].model == "some-future-model"


async def test_health_reports_configured_and_cooling_state() -> None:
    router, _ = make_router(
        llm=[FakeLLM("live"), FakeLLM("nokey", configured=False)],
        tts={"ko": [FakeTTS("azure")]},
    )
    await router.breaker.trip("llm", "live", 60)
    health = {(h.capability, h.provider): h for h in await router.health()}
    assert health[("llm", "live")].state == "cooling"
    assert health[("llm", "nokey")].state == "unconfigured"
    assert health[("tts", "azure")].state == "ok"


async def test_accounting_failure_never_breaks_a_turn() -> None:
    async def explode(event: UsageEvent) -> None:
        raise RuntimeError("ledger is down")

    router, _ = make_router(llm=[FakeLLM("primary", text="still works")])
    router.set_recorder(explode)
    provider, text = await collect(router.llm_stream([Msg("user", "hi")]))
    assert provider == "primary"
    assert text.strip() == "still works"

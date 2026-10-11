"""Builds the provider chains from configuration.

`TS_PROVIDER_MODE` decides what "configured" means in practice:

* `auto`  (default) — each live adapter is included when its key is present,
  and the last-resort adapter is always appended.  An empty `.env` therefore
  yields a fully working mock stack.
* `mock`  — only the offline adapters.  This is what the test suite uses.
* `live`  — refuses to start unless at least one live LLM and one live STT are
  configured, so a production deploy cannot quietly serve mock output.
"""

from __future__ import annotations

import logging

from ..core.config import Settings, get_settings
from .base import LLMProvider, PronunciationProvider, STTProvider, TTSProvider
from .llm.mock import MockLLM
from .llm.openai_compat import OpenAICompatLLM
from .pron.azure import AzurePronunciation
from .pron.heuristic import HeuristicPronunciation
from .router import ProviderRouter
from .stt.azure import AzureSTT
from .stt.deepgram import DeepgramSTT
from .stt.groq_whisper import GroqWhisperSTT
from .stt.mock import MockSTT
from .tts.azure import AzureTTS
from .tts.deepgram import DeepgramTTS
from .tts.mock import MockTTS

log = logging.getLogger("talkscene.providers")

LANGS = ("ko", "ja", "de", "en")


class LiveProviderMissing(RuntimeError):
    pass


def build_llm_chain(s: Settings) -> list[LLMProvider]:
    chain: list[LLMProvider] = []
    if s.provider_mode != "mock":
        for name in s.llm_chain:
            try:
                base_url, key, model = s.llm_credentials(name)
            except KeyError:
                log.warning("unknown LLM provider in LLM_PROVIDERS: %s", name)
                continue
            adapter = OpenAICompatLLM(name, base_url, key, model)
            if adapter.configured:
                chain.append(adapter)
    chain.append(MockLLM())
    return chain


def build_stt_chain(s: Settings) -> list[STTProvider]:
    chain: list[STTProvider] = []
    if s.provider_mode != "mock":
        for name in s.stt_chain:
            adapter: STTProvider | None = None
            if name == "groq_whisper":
                adapter = GroqWhisperSTT(s.llm_groq_base_url, s.groq_api_key, s.stt_groq_model)
            elif name == "deepgram":
                adapter = DeepgramSTT(s.deepgram_api_key, s.stt_deepgram_model)
            elif name == "azure":
                adapter = AzureSTT(s.azure_speech_key, s.azure_speech_region)
            else:
                log.warning("unknown STT provider in STT_PROVIDERS: %s", name)
            if adapter is not None and adapter.configured:
                chain.append(adapter)
    chain.append(MockSTT())
    return chain


def build_tts_chains(s: Settings) -> dict[str, list[TTSProvider]]:
    """Per-language chains: the capability matrix is not uniform (no Korean on Aura-2)."""
    azure = AzureTTS(s.azure_speech_key, s.azure_speech_region)
    deepgram = DeepgramTTS(s.deepgram_api_key, s.tts_deepgram_model)
    chains: dict[str, list[TTSProvider]] = {}
    for lang in LANGS:
        chain: list[TTSProvider] = []
        if s.provider_mode != "mock":
            for name in s.tts_chain(lang):
                if name == "azure" and azure.configured:
                    chain.append(azure)
                elif name == "deepgram" and deepgram.configured and deepgram.supports(lang):
                    chain.append(deepgram)
                elif name == "browser":
                    # Resolved in the client; nothing for the server to call.
                    continue
        chain.append(MockTTS())
        chains[lang] = chain
    return chains


def build_pron_chain(s: Settings, stt_chain: list[STTProvider]) -> list[PronunciationProvider]:
    chain: list[PronunciationProvider] = []
    if s.provider_mode != "mock" and s.pron_provider == "azure":
        azure = AzurePronunciation(s.azure_speech_key, s.azure_speech_region)
        if azure.configured:
            chain.append(azure)
    # The heuristic fallback reuses whatever STT is first in the chain.
    chain.append(HeuristicPronunciation(stt_chain[0]))
    return chain


def build_router(settings: Settings | None = None) -> ProviderRouter:
    s = settings or get_settings()
    llm = build_llm_chain(s)
    stt = build_stt_chain(s)
    tts = build_tts_chains(s)
    pron = build_pron_chain(s, stt)

    if s.provider_mode == "live":
        live_llm = [p for p in llm if p.name != "mock"]
        live_stt = [p for p in stt if p.name != "mock"]
        if not live_llm or not live_stt:
            raise LiveProviderMissing(
                "TS_PROVIDER_MODE=live but no live "
                f"{'LLM' if not live_llm else 'STT'} provider is configured. "
                "Set GROQ_API_KEY (or another provider key), or use TS_PROVIDER_MODE=auto."
            )

    log.info(
        "provider chains built",
        extra={
            "extra_fields": {
                "mode": s.provider_mode,
                "llm": [p.name for p in llm],
                "stt": [p.name for p in stt],
                "tts": {lang: [p.name for p in chain] for lang, chain in tts.items()},
                "pron": [p.name for p in pron],
            }
        },
    )
    return ProviderRouter(llm=llm, stt=stt, tts=tts, pron=pron)


_router: ProviderRouter | None = None


def get_router() -> ProviderRouter:
    global _router
    if _router is None:
        _router = build_router()
    return _router


def set_router(router: ProviderRouter | None) -> None:
    global _router
    _router = router


# ── BYOK: a per-learner router built from their own keys ────────────────────
_BYOK_FIELDS = {
    "groq": "groq_api_key",
    "xai": "xai_api_key",
    "gemini": "gemini_api_key",
    "deepgram": "deepgram_api_key",
    "azure_speech_key": "azure_speech_key",
    "azure_speech_region": "azure_speech_region",
}

_byok_cache: dict[str, ProviderRouter] = {}
_BYOK_CACHE_MAX = 256


def build_user_router(keys: dict[str, str]) -> ProviderRouter:
    """Router that spends the learner's own quota instead of the service's.

    Cached by a digest of the key material so repeated requests reuse one set of
    adapters (and therefore one set of token buckets).
    """
    import hashlib

    overrides = {field: keys[name] for name, field in _BYOK_FIELDS.items() if keys.get(name)}
    if not overrides:
        return get_router()

    digest = hashlib.sha256(
        "|".join(f"{k}={v}" for k, v in sorted(overrides.items())).encode()
    ).hexdigest()
    cached = _byok_cache.get(digest)
    if cached is not None:
        return cached

    # BYOK implies live providers: without this the learner's key would be
    # ignored whenever the service itself is running on mocks.
    s = get_settings().model_copy(update={**overrides, "provider_mode": "auto"})
    router = build_router(s)
    if len(_byok_cache) >= _BYOK_CACHE_MAX:
        _byok_cache.clear()
    _byok_cache[digest] = router
    return router

"""Provider protocols and the value types they exchange (plan §10.3).

Four capabilities, four protocols.  Adapters implement exactly one and know
nothing about the router, the database or FastAPI, which is what makes them
cheap to add and possible to unit-test offline.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Capability = Literal["llm", "stt", "tts", "pron"]
Role = Literal["system", "user", "assistant"]


# ── exchanged values ─────────────────────────────────────────────────────────
@dataclass(slots=True)
class Msg:
    role: Role
    content: str


@dataclass(slots=True)
class Word:
    """One recognised word with its timing and the model's confidence.

    `prob` is a *confidence hint only* — see ADR 0003.  It is never turned into
    a pronunciation score.
    """

    w: str
    start: float
    end: float
    prob: float = 1.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(slots=True)
class STTResult:
    text: str
    words: list[Word] = field(default_factory=list)
    no_speech_prob: float = 0.0
    duration_s: float = 0.0
    language: str = ""
    provider: str = ""
    avg_logprob: float | None = None


@dataclass(slots=True)
class AudioChunk:
    data: bytes
    content_type: str = "audio/mpeg"
    voice: str = ""
    provider: str = ""
    chars: int = 0
    cached: bool = False


@dataclass(slots=True)
class PhonemeScore:
    phoneme: str
    score: float


@dataclass(slots=True)
class WordScore:
    word: str
    accuracy: float
    error_type: str = "None"  # None | Mispronunciation | Omission | Insertion
    phonemes: list[PhonemeScore] = field(default_factory=list)


@dataclass(slots=True)
class PAResult:
    """Scripted pronunciation assessment (ADR 0003, track 2)."""

    accuracy: float
    fluency: float
    completeness: float
    prosody: float | None
    recognized_text: str
    words: list[WordScore] = field(default_factory=list)
    provider: str = ""
    # True only when real phoneme-level assessment happened. The UI must not
    # show a phoneme strip or a hard score when this is False.
    authoritative: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "accuracy": self.accuracy,
            "fluency": self.fluency,
            "completeness": self.completeness,
            "prosody": self.prosody,
            "recognized_text": self.recognized_text,
            "provider": self.provider,
            "authoritative": self.authoritative,
            "words": [
                {
                    "word": w.word,
                    "accuracy": w.accuracy,
                    "error_type": w.error_type,
                    "phonemes": [{"phoneme": p.phoneme, "score": p.score} for p in w.phonemes],
                }
                for w in self.words
            ],
        }


# ── failures the router understands ──────────────────────────────────────────
class ProviderError(Exception):
    """Base: this provider failed, try the next one."""

    def __init__(self, provider: str, detail: str) -> None:
        self.provider = provider
        self.detail = detail
        super().__init__(f"{provider}: {detail}")


class ProviderRateLimited(ProviderError):
    def __init__(self, provider: str, retry_after_s: float = 30.0) -> None:
        self.retry_after_s = retry_after_s
        super().__init__(provider, f"rate limited, retry after {retry_after_s:.0f}s")


class ProviderUnavailable(ProviderError):
    """5xx, timeout, or connection refused."""


class ProviderNotConfigured(ProviderError):
    def __init__(self, provider: str) -> None:
        super().__init__(provider, "no credentials configured")


# ── protocols ────────────────────────────────────────────────────────────────
@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    @property
    def configured(self) -> bool: ...

    def chat_stream(
        self,
        messages: list[Msg],
        *,
        temperature: float = 0.7,
        max_tokens: int = 320,
        json_mode: bool = False,
        stop: list[str] | None = None,
    ) -> AsyncIterator[str]: ...


@runtime_checkable
class STTProvider(Protocol):
    name: str

    @property
    def configured(self) -> bool: ...

    async def transcribe(
        self,
        audio: bytes,
        *,
        lang: str,
        prompt: str | None = None,
        content_type: str = "audio/webm",
        client_transcript: str | None = None,
    ) -> STTResult: ...


@runtime_checkable
class TTSProvider(Protocol):
    name: str

    @property
    def configured(self) -> bool: ...

    def voice_for(self, lang: str, preferred: str | None = None) -> str: ...

    async def synthesize(
        self, text: str, *, lang: str, voice: str | None = None, rate: float = 1.0
    ) -> AudioChunk: ...


@runtime_checkable
class PronunciationProvider(Protocol):
    name: str

    @property
    def configured(self) -> bool: ...

    async def assess(
        self, audio: bytes, *, lang: str, reference_text: str, content_type: str = "audio/wav"
    ) -> PAResult: ...


# ── shared locale helpers ────────────────────────────────────────────────────
LOCALES: dict[str, str] = {"ko": "ko-KR", "ja": "ja-JP", "de": "de-DE", "en": "en-US"}
LANGUAGE_NAMES: dict[str, str] = {
    "ko": "Korean",
    "ja": "Japanese",
    "de": "German",
    "en": "English",
}


def locale_for(lang: str) -> str:
    return LOCALES.get(lang, "en-US")

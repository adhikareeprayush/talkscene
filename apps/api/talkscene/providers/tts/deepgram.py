"""Deepgram Aura-2 TTS.

Deliberately refuses Korean.  Aura-2 covers en, es, nl, fr, de, it and ja only
(plan §3.3), and a provider that silently synthesises the wrong language is
worse than one that fails over.
"""

from __future__ import annotations

import httpx

from ..base import AudioChunk, ProviderNotConfigured, ProviderUnavailable
from ..http import client, raise_for_provider, transport_error

ENDPOINT = "https://api.deepgram.com/v1/speak"

# No Korean entry: that absence is the point.
VOICES: dict[str, str] = {
    "en": "aura-2-thalia-en",
    "de": "aura-2-vesta-de",
    "ja": "aura-2-asuka-ja",
}
SUPPORTED = frozenset(VOICES)


class DeepgramTTS:
    name = "deepgram"

    def __init__(self, api_key: str, default_model: str) -> None:
        self.api_key = api_key
        self.default_model = default_model

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def supports(self, lang: str) -> bool:
        return lang in SUPPORTED

    def voice_for(self, lang: str, preferred: str | None = None) -> str:
        if preferred and preferred.startswith("aura"):
            return preferred
        return VOICES.get(lang, self.default_model)

    async def synthesize(
        self, text: str, *, lang: str, voice: str | None = None, rate: float = 1.0
    ) -> AudioChunk:
        if not self.configured:
            raise ProviderNotConfigured(self.name)
        if not self.supports(lang):
            raise ProviderUnavailable(self.name, f"Aura-2 has no {lang} voice")
        model = self.voice_for(lang, voice)
        try:
            resp = await client().post(
                ENDPOINT,
                params={"model": model, "encoding": "mp3"},
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"text": text},
            )
        except httpx.HTTPError as exc:
            raise transport_error(self.name, exc) from exc
        raise_for_provider(self.name, resp)
        # Aura-2 has no rate parameter; the client time-stretches for slow replay.
        return AudioChunk(
            data=resp.content,
            content_type="audio/mpeg",
            voice=model,
            provider=self.name,
            chars=len(text),
        )

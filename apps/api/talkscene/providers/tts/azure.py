"""Azure Neural TTS over the REST endpoint — the premium voice tier.

Primary for Korean, because the free alternative with the best quality
(Deepgram Aura-2) has no Korean at all (plan §3.3).  Note the billing quirk:
CJK characters count double toward the 0.5M/month F0 allowance, which is why
`chars` is reported back for the usage ledger.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

import httpx

from ..base import AudioChunk, ProviderNotConfigured, locale_for
from ..http import client, raise_for_provider, transport_error

# Plan §20.2. Verify availability in the Azure voice gallery before relying on one.
VOICES: dict[str, str] = {
    "ko": "ko-KR-SunHiNeural",
    "ja": "ja-JP-NanamiNeural",
    "de": "de-DE-KatjaNeural",
    "en": "en-US-JennyNeural",
}
OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"


class AzureTTS:
    name = "azure"

    def __init__(self, key: str, region: str) -> None:
        self.key = key
        self.region = region

    @property
    def configured(self) -> bool:
        return bool(self.key and self.region)

    @property
    def endpoint(self) -> str:
        return f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1"

    def voice_for(self, lang: str, preferred: str | None = None) -> str:
        if preferred and preferred.startswith(locale_for(lang)[:2]):
            return preferred
        return VOICES.get(lang, VOICES["en"])

    def _ssml(self, text: str, lang: str, voice: str, rate: float) -> str:
        # Azure wants a relative percentage, where 1.0 == "+0%".
        pct = round((rate - 1.0) * 100)
        rate_attr = f"{pct:+d}%"
        return (
            f'<speak version="1.0" xml:lang="{locale_for(lang)}" '
            'xmlns="http://www.w3.org/2001/10/synthesis">'
            f'<voice name="{voice}">'
            f'<prosody rate="{rate_attr}">{escape(text)}</prosody>'
            "</voice></speak>"
        )

    async def synthesize(
        self, text: str, *, lang: str, voice: str | None = None, rate: float = 1.0
    ) -> AudioChunk:
        if not self.configured:
            raise ProviderNotConfigured(self.name)
        chosen = self.voice_for(lang, voice)
        try:
            resp = await client().post(
                self.endpoint,
                headers={
                    "Ocp-Apim-Subscription-Key": self.key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
                    "User-Agent": "talkscene",
                },
                content=self._ssml(text, lang, chosen, rate).encode(),
            )
        except httpx.HTTPError as exc:
            raise transport_error(self.name, exc) from exc
        raise_for_provider(self.name, resp)
        return AudioChunk(
            data=resp.content,
            content_type="audio/mpeg",
            voice=chosen,
            provider=self.name,
            chars=billed_chars(text, lang),
        )


def billed_chars(text: str, lang: str) -> int:
    """CJK characters are billed double on Azure Neural TTS (plan §3.3)."""
    return len(text) * 2 if lang in ("ko", "ja") else len(text)

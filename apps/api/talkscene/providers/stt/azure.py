"""Azure Speech short-audio STT.

Present mainly because the same resource powers Pronunciation Assessment, so a
deployment that has an Azure key gets STT failover for free.  The short-audio
endpoint accepts at most 60 s of audio.
"""

from __future__ import annotations

import httpx

from ..base import ProviderNotConfigured, STTResult, Word, locale_for
from ..http import client, raise_for_provider, transport_error


class AzureSTT:
    name = "azure"

    def __init__(self, key: str, region: str) -> None:
        self.key = key
        self.region = region

    @property
    def configured(self) -> bool:
        return bool(self.key and self.region)

    @property
    def endpoint(self) -> str:
        return (
            f"https://{self.region}.stt.speech.microsoft.com"
            "/speech/recognition/conversation/cognitiveservices/v1"
        )

    async def transcribe(
        self,
        audio: bytes,
        *,
        lang: str,
        prompt: str | None = None,
        content_type: str = "audio/webm",
        client_transcript: str | None = None,
    ) -> STTResult:
        if not self.configured:
            raise ProviderNotConfigured(self.name)
        try:
            resp = await client().post(
                self.endpoint,
                params={
                    "language": locale_for(lang),
                    "format": "detailed",
                    "wordLevelTimestamps": "true",
                },
                headers={
                    "Ocp-Apim-Subscription-Key": self.key,
                    "Content-Type": _azure_content_type(content_type),
                    "Accept": "application/json",
                },
                content=audio,
            )
        except httpx.HTTPError as exc:
            raise transport_error(self.name, exc) from exc
        raise_for_provider(self.name, resp)

        body = resp.json()
        if body.get("RecognitionStatus") != "Success":
            return STTResult(text="", provider=self.name, no_speech_prob=1.0, language=lang)
        best = (body.get("NBest") or [{}])[0]
        words = [
            Word(
                w=w.get("Word", ""),
                start=w.get("Offset", 0) / 1e7,
                end=(w.get("Offset", 0) + w.get("Duration", 0)) / 1e7,
                prob=float(best.get("Confidence", 1.0)),
            )
            for w in best.get("Words", [])
        ]
        return STTResult(
            text=(best.get("Display") or body.get("DisplayText") or "").strip(),
            words=words,
            duration_s=body.get("Duration", 0) / 1e7,
            language=lang,
            provider=self.name,
        )


def _azure_content_type(content_type: str) -> str:
    """Azure needs an explicit codec declaration, not a bare mime type."""
    if "webm" in content_type or "opus" in content_type:
        return 'audio/webm; codecs="opus"'
    if "ogg" in content_type:
        return 'audio/ogg; codecs="opus"'
    return "audio/wav; codecs=audio/pcm; samplerate=16000"

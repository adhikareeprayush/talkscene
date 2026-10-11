"""Deepgram Nova-3 — optional STT, funded by the one-time $200 credit.

Nova-3 returns a real per-word `confidence`, which makes it the better source
for the unclear-word hints when a key is present.
"""

from __future__ import annotations

import httpx

from ..base import ProviderNotConfigured, STTResult, Word
from ..http import client, raise_for_provider, transport_error

ENDPOINT = "https://api.deepgram.com/v1/listen"


class DeepgramSTT:
    name = "deepgram"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

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
        params = {
            "model": self.model,
            "language": lang,
            "smart_format": "true",
            "punctuate": "true",
        }
        if prompt:
            # Nova-3 keyterm prompting: bias toward the scenario's vocabulary.
            params["keyterm"] = prompt[:200]
        try:
            resp = await client().post(
                ENDPOINT,
                params=params,
                headers={"Authorization": f"Token {self.api_key}", "Content-Type": content_type},
                content=audio,
            )
        except httpx.HTTPError as exc:
            raise transport_error(self.name, exc) from exc
        raise_for_provider(self.name, resp)

        body = resp.json()
        try:
            alt = body["results"]["channels"][0]["alternatives"][0]
        except (KeyError, IndexError):
            return STTResult(text="", provider=self.name, no_speech_prob=1.0, language=lang)
        words = [
            Word(
                w=w.get("punctuated_word") or w.get("word", ""),
                start=float(w.get("start", 0.0)),
                end=float(w.get("end", 0.0)),
                prob=float(w.get("confidence", 1.0)),
            )
            for w in alt.get("words", [])
        ]
        transcript = (alt.get("transcript") or "").strip()
        return STTResult(
            text=transcript,
            words=words,
            no_speech_prob=0.0 if transcript else 1.0,
            duration_s=float(body.get("metadata", {}).get("duration", 0.0)),
            language=lang,
            provider=self.name,
        )

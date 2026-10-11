"""Groq-hosted Whisper — the primary final transcript (plan §7.2).

Whisper does not return per-word probabilities, only a per-segment
`avg_logprob`.  We convert that to a word-level confidence hint by inheriting
the containing segment's value, which is why ADR 0003 treats these numbers as
*hints* and never as a pronunciation score.
"""

from __future__ import annotations

import math

import httpx

from ..base import ProviderNotConfigured, STTResult, Word
from ..http import client, raise_for_provider, transport_error


class GroqWhisperSTT:
    name = "groq_whisper"

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
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

        # The live browser transcript is a genuinely useful spelling bias, so it
        # is folded into the Whisper prompt alongside the scenario vocabulary.
        bias = " ".join(p for p in (prompt, client_transcript) if p).strip()[:880]

        data = {
            "model": self.model,
            "language": lang,  # always pinned: avoids misdetection
            "temperature": "0",
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        }
        if bias:
            data["prompt"] = bias

        try:
            resp = await client().post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=data,
                files={"file": ("turn.webm", audio, content_type)},
            )
        except httpx.HTTPError as exc:
            raise transport_error(self.name, exc) from exc
        raise_for_provider(self.name, resp)
        return self._parse(resp.json(), lang)

    def _parse(self, body: dict, lang: str) -> STTResult:
        segments = body.get("segments") or []
        no_speech = max((s.get("no_speech_prob", 0.0) for s in segments), default=0.0)
        avg_logprob = (
            sum(s.get("avg_logprob", 0.0) for s in segments) / len(segments) if segments else None
        )

        def seg_prob(t: float) -> float:
            for s in segments:
                if s.get("start", 0.0) <= t <= s.get("end", 0.0):
                    return min(1.0, math.exp(s.get("avg_logprob", -0.2)))
            return min(1.0, math.exp(avg_logprob)) if avg_logprob is not None else 1.0

        words = [
            Word(
                w=w.get("word", "").strip(),
                start=float(w.get("start", 0.0)),
                end=float(w.get("end", 0.0)),
                prob=round(seg_prob(float(w.get("start", 0.0))), 4),
            )
            for w in (body.get("words") or [])
            if w.get("word", "").strip()
        ]
        return STTResult(
            text=(body.get("text") or "").strip(),
            words=words,
            no_speech_prob=float(no_speech),
            duration_s=float(body.get("duration") or (words[-1].end if words else 0.0)),
            language=body.get("language") or lang,
            provider=self.name,
            avg_logprob=avg_logprob,
        )

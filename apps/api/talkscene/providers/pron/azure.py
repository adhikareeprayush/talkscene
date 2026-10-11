"""Azure Pronunciation Assessment — the only authoritative scorer here.

Reached over the short-audio REST endpoint with the `Pronunciation-Assessment`
header rather than the Speech SDK, which would add a large native dependency to
the API image (ADR 0003).  Scripted mode only: a known reference text is its
most reliable configuration, and drills always have one.
"""

from __future__ import annotations

import base64
import json

import httpx

from ...core.audio import to_wav16k
from ..base import (
    PAResult,
    PhonemeScore,
    ProviderNotConfigured,
    ProviderUnavailable,
    WordScore,
    locale_for,
)
from ..http import client, raise_for_provider, transport_error

# Prosody assessment is not available in every locale - verify per language.
PROSODY_LOCALES = frozenset({"en-US", "en-GB", "ja-JP", "de-DE", "ko-KR"})


class AzurePronunciation:
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

    def _header(self, reference_text: str, locale: str) -> str:
        params = {
            "ReferenceText": reference_text,
            "GradingSystem": "HundredMark",
            "Granularity": "Phoneme",
            # Miscue detection off: a learner skipping a word should score as
            # incomplete, not derail the whole alignment.
            "EnableMiscue": "False",
            "Dimension": "Comprehensive",
        }
        if locale in PROSODY_LOCALES:
            params["EnableProsodyAssessment"] = "True"
        return base64.b64encode(json.dumps(params).encode()).decode()

    async def assess(
        self, audio: bytes, *, lang: str, reference_text: str, content_type: str = "audio/wav"
    ) -> PAResult:
        if not self.configured:
            raise ProviderNotConfigured(self.name)

        wav = await to_wav16k(audio, content_type)
        if wav is None:
            raise ProviderUnavailable(
                self.name, "cannot transcode to 16kHz mono PCM (ffmpeg not installed)"
            )

        locale = locale_for(lang)
        try:
            resp = await client().post(
                self.endpoint,
                params={"language": locale, "format": "detailed"},
                headers={
                    "Ocp-Apim-Subscription-Key": self.key,
                    "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                    "Pronunciation-Assessment": self._header(reference_text, locale),
                    "Accept": "application/json",
                },
                content=wav,
            )
        except httpx.HTTPError as exc:
            raise transport_error(self.name, exc) from exc
        raise_for_provider(self.name, resp)

        body = resp.json()
        if body.get("RecognitionStatus") != "Success":
            raise ProviderUnavailable(
                self.name, f"recognition status {body.get('RecognitionStatus')}"
            )
        best = (body.get("NBest") or [{}])[0]
        scores = best.get("PronunciationAssessment", {})

        words: list[WordScore] = []
        for w in best.get("Words", []):
            wa = w.get("PronunciationAssessment", {})
            words.append(
                WordScore(
                    word=w.get("Word", ""),
                    accuracy=float(wa.get("AccuracyScore", 0.0)),
                    error_type=wa.get("ErrorType", "None"),
                    phonemes=[
                        PhonemeScore(
                            phoneme=p.get("Phoneme", ""),
                            score=float(
                                p.get("PronunciationAssessment", {}).get("AccuracyScore", 0.0)
                            ),
                        )
                        for p in w.get("Phonemes", [])
                    ],
                )
            )

        prosody = scores.get("ProsodyScore")
        return PAResult(
            accuracy=float(scores.get("AccuracyScore", 0.0)),
            fluency=float(scores.get("FluencyScore", 0.0)),
            completeness=float(scores.get("CompletenessScore", 0.0)),
            prosody=float(prosody) if prosody is not None else None,
            recognized_text=best.get("Display", "") or body.get("DisplayText", ""),
            words=words,
            provider=self.name,
            authoritative=True,
        )

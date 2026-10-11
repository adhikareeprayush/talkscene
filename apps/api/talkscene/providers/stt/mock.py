"""Offline STT.

Transcription cannot be invented from bytes, so this adapter does the one honest
thing available: it echoes the browser's live transcript when the client sent
one, and otherwise returns a short language-appropriate placeholder.  Word
timings are synthesised from the audio length so the fluency maths and the
unclear-word path in `engine/fluency.py` are exercised for real.
"""

from __future__ import annotations

import hashlib

from ...core.audio import estimate_duration_s, peak_rms
from ..base import STTResult, Word

PLACEHOLDER = {
    "ko": "네, 알겠어요.",
    "ja": "はい、わかりました。",
    "de": "Ja, alles klar.",
    "en": "Yes, that sounds good.",
}

CJK = ("ko", "ja")
# Below this RMS the clip is silence, and a real engine would return nothing.
SILENCE_RMS = 0.004


def _tokens(text: str, lang: str) -> list[str]:
    """Match how the real providers segment: Korean and Japanese have no spaces,
    so Whisper returns short character groups rather than whitespace words."""
    if lang in CJK:
        return [ch for ch in text if not ch.isspace()] or [text]
    return text.split() or [text]


class MockSTT:
    name = "mock"

    @property
    def configured(self) -> bool:
        return True

    async def transcribe(
        self,
        audio: bytes,
        *,
        lang: str,
        prompt: str | None = None,
        content_type: str = "audio/webm",
        client_transcript: str | None = None,
    ) -> STTResult:
        duration = max(0.6, min(30.0, estimate_duration_s(audio, content_type))) if audio else 1.6

        # Silence in, nothing out - the orchestrator then returns `no_speech`
        # and does not charge the learner a turn.
        rms = peak_rms(audio) if audio else None
        if rms is not None and rms < SILENCE_RMS:
            return STTResult(
                text="",
                no_speech_prob=0.96,
                duration_s=round(duration, 3),
                language=lang,
                provider=self.name,
            )

        text = (client_transcript or "").strip() or PLACEHOLDER.get(lang, PLACEHOLDER["en"])

        tokens = _tokens(text, lang)
        slot = duration / len(tokens)
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        # Mark one word as low confidence so the "estimated unclear" path in the
        # report has something to show offline.
        unclear = seed % len(tokens)

        words = [
            Word(
                w=tok,
                start=round(i * slot, 3),
                end=round((i + 1) * slot - 0.02, 3),
                prob=0.42 if i == unclear and len(tokens) > 1 else 0.95,
            )
            for i, tok in enumerate(tokens)
        ]
        return STTResult(
            text=text,
            words=words,
            no_speech_prob=0.02,
            duration_s=round(duration, 3),
            language=lang,
            provider=self.name,
            avg_logprob=-0.25,
        )

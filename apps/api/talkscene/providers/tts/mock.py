"""Offline TTS.

Returns a genuine, playable WAV of the right duration rather than an empty
body, so the audio queue, the `<audio>` element, the replay controls and the
slow-replay path all work with no keys.  It is silent on purpose: the client
sees `provider: "mock"` on the turn and speaks the line with the browser's own
`speechSynthesis`, which is the always-on fallback the plan specifies (§7.4).
"""

from __future__ import annotations

import io
import struct
import wave

from ..base import AudioChunk

SAMPLE_RATE = 16_000
# Rough speaking rates, used only to make the silent clip the right length.
CHARS_PER_SECOND = {"ko": 6.0, "ja": 6.5, "de": 14.0, "en": 15.0}


def silent_wav(seconds: float) -> bytes:
    frames = max(1, int(SAMPLE_RATE * seconds))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(struct.pack("<h", 0) * frames)
    return buf.getvalue()


class MockTTS:
    name = "mock"

    @property
    def configured(self) -> bool:
        return True

    def voice_for(self, lang: str, preferred: str | None = None) -> str:
        return preferred or f"mock-{lang}"

    async def synthesize(
        self, text: str, *, lang: str, voice: str | None = None, rate: float = 1.0
    ) -> AudioChunk:
        cps = CHARS_PER_SECOND.get(lang, 14.0) * max(rate, 0.1)
        seconds = min(30.0, max(0.5, len(text) / cps))
        return AudioChunk(
            data=silent_wav(seconds),
            content_type="audio/wav",
            voice=self.voice_for(lang, voice),
            provider=self.name,
            chars=len(text),
        )

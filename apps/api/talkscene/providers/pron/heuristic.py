"""Non-authoritative pronunciation fallback.

Used when Azure is unconfigured, out of free quota, or ffmpeg is unavailable.
It transcribes the attempt with whatever STT is available and compares that
against the known reference text, which catches *wrong or missing words* — the
thing an STT transcript genuinely evidences.

It cannot hear phonemes, so `prosody` is None, `words[].phonemes` is empty and
`authoritative` is False.  The UI is required to label these numbers as
estimated and to hide the phoneme strip (ADR 0003).
"""

from __future__ import annotations

import difflib
import re

from ..base import PAResult, STTProvider, WordScore

_PUNCT = re.compile(r"[^\w぀-ヿ㐀-䶿一-鿿가-힯]+", re.UNICODE)


def tokenize(text: str, lang: str) -> list[str]:
    """Whitespace tokens for de/en; per-character for ko/ja, which do not space."""
    cleaned = _PUNCT.sub(" ", text).strip()
    if lang in ("ko", "ja"):
        return [ch for ch in cleaned if not ch.isspace()]
    return cleaned.lower().split()


class HeuristicPronunciation:
    name = "heuristic"

    def __init__(self, stt: STTProvider) -> None:
        self._stt = stt

    @property
    def configured(self) -> bool:
        return True

    async def assess(
        self, audio: bytes, *, lang: str, reference_text: str, content_type: str = "audio/wav"
    ) -> PAResult:
        stt = await self._stt.transcribe(
            audio, lang=lang, prompt=reference_text, content_type=content_type
        )
        said = stt.text
        ref_tokens = tokenize(reference_text, lang)
        said_tokens = tokenize(said, lang)

        matcher = difflib.SequenceMatcher(None, ref_tokens, said_tokens)
        similarity = matcher.ratio()

        matched: set[int] = set()
        for block in matcher.get_matching_blocks():
            matched.update(range(block.a, block.a + block.size))

        # Per-word confidence from the STT hints, aligned positionally.
        conf_by_token = {w.w.strip().lower(): w.prob for w in stt.words}
        words = [
            WordScore(
                word=tok,
                accuracy=round(
                    100.0 * (0.9 if i in matched else 0.25) * conf_by_token.get(tok.lower(), 0.95),
                    1,
                ),
                error_type="None" if i in matched else "Mispronunciation",
            )
            for i, tok in enumerate(ref_tokens)
        ]

        completeness = 100.0 * (len(matched) / len(ref_tokens)) if ref_tokens else 0.0
        # Fluency proxy: speech rate against a per-language comfortable rate.
        expected_s = len(ref_tokens) / {"ko": 5.0, "ja": 5.5, "de": 2.4, "en": 2.6}.get(lang, 2.6)
        if stt.duration_s > 0 and expected_s > 0:
            ratio = min(stt.duration_s / expected_s, expected_s / stt.duration_s)
            fluency = round(55.0 + 45.0 * max(0.0, min(1.0, ratio)), 1)
        else:
            fluency = 60.0

        return PAResult(
            accuracy=round(100.0 * (0.35 + 0.65 * similarity), 1),
            fluency=fluency,
            completeness=round(completeness, 1),
            prosody=None,
            recognized_text=said,
            words=words,
            provider=self.name,
            authoritative=False,
        )

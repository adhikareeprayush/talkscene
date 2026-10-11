"""Sentence chunking for streamed TTS (plan §7.4).

Synthesising sentence 1 while the model is still writing sentence 2 is what
gets first-audio under a second.  Two rules matter in practice:

* CJK sentence enders (。！？) carry no following space, and Korean/Japanese
  text often has no spaces at all, so splitting on whitespace would never fire.
* A fragment must not be flushed too early: "A." in "Mr. A. Smith" or a decimal
  point would produce a one-word audio clip.  Hence the minimum length — which
  is **per language**, because a complete Korean sentence ("네, 알겠습니다.") is
  nine characters where the English equivalent is twenty. A single Latin-sized
  threshold would merge two CJK sentences into one clip and delay first audio.
"""

from __future__ import annotations

import re

TERMINATORS = "。．！？!?…"
MIN_CHUNK_CHARS = {"ko": 6, "ja": 6, "de": 12, "en": 12}
DEFAULT_MIN_CHARS = 12
MAX_CHUNK_CHARS = 180

_SPLIT = re.compile(r"(?<=[。．！？!?…])\s*|(?<=[.!?])\s+")


def min_chars_for(lang: str | None) -> int:
    return MIN_CHUNK_CHARS.get(lang or "", DEFAULT_MIN_CHARS)


def split_sentences(text: str, lang: str | None = None) -> list[str]:
    """Split a complete reply into synthesisable sentences."""
    minimum = min_chars_for(lang)
    parts = [p.strip() for p in _SPLIT.split(text.strip()) if p and p.strip()]
    merged: list[str] = []
    for part in parts:
        # Fold fragments shorter than the minimum into the previous sentence.
        if merged and len(part) < minimum and len(merged[-1]) + len(part) <= MAX_CHUNK_CHARS:
            merged[-1] = f"{merged[-1]} {part}".strip()
        else:
            merged.append(part)
    return merged or ([text.strip()] if text.strip() else [])


class StreamChunker:
    """Incremental splitter for an LLM token stream.

    Feed deltas, take whole sentences as they complete, then `flush()` the tail.
    """

    def __init__(
        self,
        lang: str | None = None,
        *,
        min_chars: int | None = None,
        max_chars: int = MAX_CHUNK_CHARS,
    ) -> None:
        self._buf = ""
        self.min_chars = min_chars if min_chars is not None else min_chars_for(lang)
        self.max_chars = max_chars

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        out: list[str] = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            chunk, self._buf = self._buf[:cut].strip(), self._buf[cut:].lstrip()
            if chunk:
                out.append(chunk)
        return out

    def _find_cut(self) -> int | None:
        for i, ch in enumerate(self._buf):
            if ch in TERMINATORS and i + 1 >= self.min_chars:
                return i + 1
            # Latin '.' needs a following space to count, which protects
            # decimals and abbreviations - and mid-stream means "wait for more".
            if ch in ".!?" and i + 1 >= self.min_chars and self._buf[i + 1 : i + 2] in (" ", "\n"):
                return i + 1
        if len(self._buf) >= self.max_chars:
            # Hard cap: break at the last space before the limit so we never
            # hand a 500-character paragraph to a TTS endpoint.
            window = self._buf[: self.max_chars]
            space = max(window.rfind(" "), window.rfind("\n"))
            return space + 1 if space > self.min_chars else self.max_chars
        return None

    def flush(self) -> str:
        tail, self._buf = self._buf.strip(), ""
        return tail

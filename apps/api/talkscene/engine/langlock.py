"""Language lock: verify the AI actually replied in the target language.

Plan §6.6 — "if the AI reply language != target, regenerate once".  Free-tier
models drift into English, especially at A1 where the instruction asks for very
simple sentences.  Script ranges catch ko/ja immediately; German and English
share the Latin alphabet, so those use function-word evidence.
"""

from __future__ import annotations

import re

HANGUL = re.compile(r"[가-힯ᄀ-ᇿ㄰-㆏]")
KANA = re.compile(r"[぀-ゟ゠-ヿ]")
CJK_IDEO = re.compile(r"[一-鿿]")
LATIN = re.compile(r"[A-Za-zÄÖÜäöüß]")

DE_MARKERS = re.compile(
    r"\b(ich|nicht|und|der|die|das|ist|sind|sie|ein|eine|haben|habe|bitte|danke|mit|"
    r"auf|für|aber|kann|können|möchte|würde|sehr|noch|schon|gern|also)\b",
    re.IGNORECASE,
)
EN_MARKERS = re.compile(
    r"\b(the|and|is|are|you|your|i|to|of|for|with|please|thanks|thank|would|could|"
    r"can|that|this|have|has|do|does|not|it|we)\b",
    re.IGNORECASE,
)

MIN_CHARS = 4


def detect(text: str) -> str:
    """Best-guess language code for a short utterance; '' when undecidable."""
    stripped = (text or "").strip()
    if len(stripped) < MIN_CHARS:
        return ""
    if HANGUL.search(stripped):
        return "ko"
    if KANA.search(stripped):
        return "ja"
    if CJK_IDEO.search(stripped) and not LATIN.search(stripped):
        # Kanji-only strings are ambiguous; Japanese is the only CJK target here.
        return "ja"
    if LATIN.search(stripped):
        de = len(DE_MARKERS.findall(stripped))
        en = len(EN_MARKERS.findall(stripped))
        if de > en:
            return "de"
        if en > de:
            return "en"
        # Umlauts or ß with no function words still point to German.
        return "de" if re.search(r"[ÄÖÜäöüß]", stripped) else "en"
    return ""


def is_on_target(text: str, lang: str) -> bool:
    """False only when we are confident the reply is in the *wrong* language."""
    detected = detect(text)
    if not detected or detected == lang:
        return True
    # A Korean or Japanese reply with a few Latin loanwords is still on target.
    if lang == "ko" and HANGUL.search(text):
        return True
    if lang == "ja" and (KANA.search(text) or CJK_IDEO.search(text)):
        return True
    if lang == "de" and detected == "en":
        # German sentences can be marker-light; require real English evidence.
        return len(EN_MARKERS.findall(text)) < 3
    return False


def latin_ratio(text: str) -> float:
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if LATIN.fullmatch(c)) / len(letters)

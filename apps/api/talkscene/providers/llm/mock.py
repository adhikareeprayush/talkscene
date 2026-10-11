"""Offline LLM, so the whole product works with an empty `.env`.

It is not a stub that returns `"ok"`.  It parses the markers the prompt
templates put in the system message (`engine/prompts.py`) and produces
structurally valid output for each of the three call shapes — roleplay turn,
end-of-session feedback, word explanation — in the right target language, with
a real `###META` tail.  That makes the full core loop, the SSE contract and the
report renderer testable without a network, and it is what the E2E suite runs
against.

Replies come from a small hand-written bank per language.  They are
deliberately generic service lines: good enough to exercise every code path,
obviously not a substitute for a real model.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import AsyncIterator

from ..base import Msg

# Per-language in-character continuations. Index 0 is never used (that is the
# scenario's own opening_line); the rest cycle.
BANK: dict[str, list[tuple[str, str, str]]] = {
    # (reply, english, romanization)
    "ko": [
        (
            "네, 알겠습니다. 성함이 어떻게 되세요?",
            "Certainly. What is your name?",
            "ne, algetseumnida. seonghami eotteoke doeseyo?",
        ),
        (
            "잠시만 기다려 주세요. 확인해 드릴게요.",
            "One moment please. I'll check for you.",
            "jamsiman gidaryeo juseyo. hwaginhae deurilgeyo.",
        ),
        (
            "아, 그렇군요. 혹시 더 필요한 거 있으세요?",
            "Ah, I see. Is there anything else you need?",
            "a, geureokunyo. hoksi deo piryohan geo isseuseyo?",
        ),
        (
            "네, 가능합니다. 몇 시쯤 괜찮으세요?",
            "Yes, that's possible. What time suits you?",
            "ne, ganeunghamnida. myeot sijjeum gwaenchaneuseyo?",
        ),
        (
            "죄송하지만 다시 한번 말씀해 주시겠어요?",
            "Sorry, could you say that once more?",
            "joesonghajiman dasi hanbeon malsseumhae jusigesseoyo?",
        ),
        (
            "알겠습니다. 그럼 그렇게 해 드릴게요.",
            "Understood. I'll arrange that then.",
            "algetseumnida. geureom geureoke hae deurilgeyo.",
        ),
        (
            "네, 맞습니다. 여기 있습니다.",
            "Yes, that's right. Here you are.",
            "ne, matseumnida. yeogi itseumnida.",
        ),
        (
            "감사합니다. 좋은 시간 보내세요!",
            "Thank you. Have a good time!",
            "gamsahamnida. joeun sigan bonaeseyo!",
        ),
    ],
    "ja": [
        (
            "はい、かしこまりました。お名前をお願いします。",
            "Certainly. Your name, please.",
            "hai, kashikomarimashita. onamae o onegaishimasu.",
        ),
        (
            "少しお待ちください。確認いたします。",
            "One moment please. I'll check.",
            "sukoshi omachi kudasai. kakunin itashimasu.",
        ),
        (
            "そうですか。ほかに何かございますか。",
            "I see. Is there anything else?",
            "sou desu ka. hoka ni nanika gozaimasu ka.",
        ),
        (
            "はい、大丈夫です。何時ごろがよろしいですか。",
            "Yes, that's fine. Around what time works?",
            "hai, daijoubu desu. nanji goro ga yoroshii desu ka.",
        ),
        (
            "すみません、もう一度おっしゃっていただけますか。",
            "Sorry, could you say that again?",
            "sumimasen, mou ichido osshatte itadakemasu ka.",
        ),
        (
            "承知しました。ではそのようにいたします。",
            "Understood. I'll do that then.",
            "shouchi shimashita. dewa sono you ni itashimasu.",
        ),
        (
            "はい、そちらになります。どうぞ。",
            "Yes, that's the one. Here you are.",
            "hai, sochira ni narimasu. douzo.",
        ),
        (
            "ありがとうございました。どうぞごゆっくり。",
            "Thank you very much. Please enjoy.",
            "arigatou gozaimashita. douzo goyukkuri.",
        ),
    ],
    "de": [
        ("Ja, gerne. Wie ist Ihr Name?", "Yes, gladly. What is your name?", ""),
        ("Einen Moment bitte, ich schaue kurz nach.", "One moment please, I'll have a look.", ""),
        ("Ach so. Brauchen Sie noch etwas?", "I see. Do you need anything else?", ""),
        ("Ja, das geht. Wann würde es Ihnen passen?", "Yes, that works. When would suit you?", ""),
        (
            "Entschuldigung, können Sie das bitte wiederholen?",
            "Sorry, could you repeat that please?",
            "",
        ),
        ("Alles klar, dann mache ich das so.", "All right, I'll do it that way then.", ""),
        ("Genau, hier bitte schön.", "Exactly — here you are.", ""),
        ("Vielen Dank und einen schönen Tag noch!", "Many thanks, and have a nice day!", ""),
    ],
    "en": [
        ("Sure, no problem. Can I take your name?", "", ""),
        ("One moment — let me check that for you.", "", ""),
        ("Right, I see. Is there anything else you need?", "", ""),
        ("Yes, we can do that. What time works for you?", "", ""),
        ("Sorry, would you mind saying that again?", "", ""),
        ("Got it. I'll sort that out for you.", "", ""),
        ("That's right. Here you go.", "", ""),
        ("Thanks a lot — have a good one!", "", ""),
    ],
}

SUGGESTIONS: dict[str, list[str]] = {
    "ko": ["네, 알겠어요.", "조금 더 천천히 말해 주세요.", "그건 얼마예요?"],
    "ja": ["はい、わかりました。", "もう少しゆっくりお願いします。", "それはいくらですか。"],
    "de": ["Ja, verstanden.", "Können Sie bitte langsamer sprechen?", "Was kostet das?"],
    "en": ["Yes, understood.", "Could you speak a bit more slowly?", "How much is that?"],
}

_LANG_BY_NAME = {"Korean": "ko", "Japanese": "ja", "German": "de", "English": "en"}


class MockLLM:
    name = "mock"
    model = "mock-roleplay-v1"

    @property
    def configured(self) -> bool:
        return True

    # ── prompt introspection ────────────────────────────────────────────────
    @staticmethod
    def _lang(system: str) -> str:
        # Roleplay prompts say "Speak ONLY in X"; feedback, explain and scenario
        # prompts name the language in their opening line instead.
        patterns = (
            r"Speak ONLY in (\w+)",
            r"You are an? (\w+) teacher",
            r"(\w+) words or grammar",
            r"for (\w+) learners",
        )
        for pattern in patterns:
            match = re.search(pattern, system)
            if match and match.group(1) in _LANG_BY_NAME:
                return _LANG_BY_NAME[match.group(1)]
        return "en"

    @staticmethod
    def _turn(system: str) -> tuple[int, int]:
        match = re.search(r"Turn (\d+) of (\d+)", system)
        return (int(match.group(1)), int(match.group(2))) if match else (1, 12)

    @staticmethod
    def _goal_ids(system: str) -> list[str]:
        return re.findall(r'"id"\s*:\s*"([a-z_][a-z0-9_]*)"', system)

    @staticmethod
    def _done_ids(system: str) -> list[str]:
        block = re.search(r"Already achieved: \[(.*?)\]", system)
        return re.findall(r'"([a-z_][a-z0-9_]*)"', block.group(1)) if block else []

    # ── the three call shapes ───────────────────────────────────────────────
    async def chat_stream(
        self,
        messages: list[Msg],
        *,
        temperature: float = 0.7,
        max_tokens: int = 320,
        json_mode: bool = False,
        stop: list[str] | None = None,
    ) -> AsyncIterator[str]:
        system = next((m.content for m in messages if m.role == "system"), "")
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")

        if "TALKSCENE_FEEDBACK_V1" in system:
            yield json.dumps(self._feedback(system, messages), ensure_ascii=False)
            return
        if "TALKSCENE_EXPLAIN_V1" in system:
            yield json.dumps(self._explain(last_user), ensure_ascii=False)
            return
        if "TALKSCENE_SCENARIO_V1" in system:
            yield json.dumps(self._scenario(system, last_user), ensure_ascii=False)
            return

        # Roleplay turn: reply text, then the ###META tail (plan §6.4).
        lang = self._lang(system)
        turn, target = self._turn(system)
        bank = BANK.get(lang, BANK["en"])
        rng = random.Random(hashlib.sha256(f"{lang}{turn}{last_user}".encode()).hexdigest())

        wrapping_up = turn >= target - 1
        reply, english, roman = bank[-1] if wrapping_up else bank[(turn - 1) % (len(bank) - 1)]

        for piece in re.findall(r"\S+\s*", reply):
            yield piece

        goal_ids = self._goal_ids(system)
        done = self._done_ids(system)
        # Credit one new goal per substantive learner utterance.
        if len(last_user.strip()) >= 2:
            remaining = [g for g in goal_ids if g not in done]
            if remaining:
                done = [*done, remaining[0]]

        meta = {
            "goals_done": done,
            "translation_en": english or reply,
            "romanization": roman,
            "suggested_replies": rng.sample(
                SUGGESTIONS.get(lang, SUGGESTIONS["en"]), k=min(3, len(SUGGESTIONS.get(lang, [])))
            ),
            "end": wrapping_up,
        }
        yield "\n###META\n"
        yield json.dumps(meta, ensure_ascii=False)

    # ── canned-but-structural payloads ──────────────────────────────────────
    def _feedback(self, system: str, messages: list[Msg]) -> dict:
        lang = self._lang(system)
        transcript = next((m.content for m in messages if m.role == "user"), "")
        learner_lines = re.findall(
            r"^\s*learner:\s*(.+)$", transcript, re.MULTILINE | re.IGNORECASE
        )
        goal_ids = self._goal_ids(system)
        said = (learner_lines[0] if learner_lines else "…").strip()[:120]
        better = {
            "ko": "김민수로 예약했어요.",
            "ja": "田中で予約しました。",
            "de": "Ich habe unter dem Namen Weber reserviert.",
            "en": "I have a reservation under the name Weber.",
        }[lang]
        return {
            "overall": 72,
            "estimated_cefr": "A2+",
            "summary": (
                "You kept the conversation going and completed most of the objectives. "
                "Work on the sentence endings and you will sound noticeably more natural."
            ),
            "goals": [
                {"id": gid, "done": i < max(1, len(goal_ids) - 1)} for i, gid in enumerate(goal_ids)
            ],
            "corrections": [
                {
                    "turn": 2,
                    "said": said,
                    "better": better,
                    "why": "Mock provider: a real model explains the grammar point here.",
                    "category": "grammar",
                }
            ],
            "vocab": {"used_well": [], "new": [], "suggested": []},
            "register": {
                "consistent": True,
                "notes": "Politeness level stayed consistent throughout.",
            },
            "next_scenario_id": None,
            "_provider_note": "Generated by the mock LLM - set a provider key for real feedback.",
        }

    @staticmethod
    def _explain(target: str) -> dict:
        word = target.strip().split()[0] if target.strip() else "…"
        return {
            "term": word,
            "reading": "",
            "meaning": "Mock explanation - configure an LLM provider for real definitions.",
            "part_of_speech": "",
            "example": "",
            "example_translation": "",
            "note": "",
        }

    @staticmethod
    def _scenario(system: str, request: str) -> dict:
        lang = MockLLM._lang(system)
        return {
            "language": lang,
            "level": "A2",
            "category": "social",
            "title": {"en": (request or "Custom scenario")[:60]},
            "summary": f"Custom practice built from: {request[:120]}",
            "persona": {
                "name": "Alex",
                "role": "Conversation partner",
                "style": "Friendly, polite.",
            },
            "setting": "A neutral everyday setting.",
            "user_role": "Yourself.",
            "goals": [
                {"id": "open", "text": "Open the conversation"},
                {"id": "explain", "text": "Explain what you want"},
                {"id": "close", "text": "Close the conversation politely"},
            ],
            "target_vocab": ["hello", "please", "thank you"],
            "target_grammar": ["polite requests"],
            "opening_line": BANK.get(lang, BANK["en"])[0][0],
            "turn_limits": {"min": 8, "default": 12, "max": 15},
        }

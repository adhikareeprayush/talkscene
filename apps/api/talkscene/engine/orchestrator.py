"""The conversation state machine (plan §6.3) and the per-turn pipeline (§7.1).

```
INIT -> BRIEFING -> AI_OPENS -> USER_TURN -> AI_TURN -+
                                   ^                  |
                                   +----- (loop) -----+
     turn_count == target  OR  goals met and the learner says goodbye
                 -> CLOSING -> ANALYZING -> REPORT_READY
```

Four decisions in here are worth knowing about:

* **The opening turn costs no LLM request.**  It is the scenario's authored
  `opening_line`, which is also why it can be TTS-cached across every learner.
  On the free-tier budget in plan §4 that is one request per session saved and a
  much faster start.
* **One LLM call per turn.**  The reply and all of its metadata (goal progress,
  translation, romanization, suggestions) come back in a single response split
  on `###META`, so hints and translations cost nothing extra (§7.3).
* **Sentence-level TTS inside the token stream.**  Sentence 1 is synthesized
  while the model is still writing sentence 2, which is what gets
  voice-to-voice into the 2-3 s budget (§7.4).
* **A rejected turn does not count.**  Silence, a failed transcription or a
  no-speech result returns `no_speech` and leaves the turn budget untouched —
  the learner is never charged a turn for a microphone problem (§11.6).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.audio import estimate_duration_s, peak_rms
from ..core.config import settings
from ..core.errors import audio_too_large, conflict, forbidden, not_found, unprocessable
from ..core.ids import session_id
from ..core.storage import get_storage, turn_audio_key
from ..models.session import PracticeSession, Turn
from ..providers.base import LANGUAGE_NAMES, Msg
from ..providers.router import ProviderRouter
from . import langlock, speech
from .chunker import StreamChunker, split_sentences
from .meta import TurnMeta, parse_json_object, parse_meta, split_reply
from .prompts import (
    explain_system_prompt,
    roleplay_system_prompt,
    sanitize_learner_text,
    summary_system_prompt,
)

log = logging.getLogger("talkscene.orchestrator")

HISTORY_WINDOW = 8  # turns sent verbatim; everything older is summarised
SUMMARY_EVERY = 6  # how often the rolling summary is refreshed
NO_SPEECH_THRESHOLD = 0.75
NOISY_RMS = 0.012
MIN_TURNS_BEFORE_END = 4


@dataclass(slots=True)
class SseEvent:
    name: str
    data: dict[str, Any] = field(default_factory=dict)


def audio_url(session_id: str, idx: int, sentence: int | None = None) -> str:
    base = f"/v1/sessions/{session_id}/turns/{idx}/audio"
    return base if sentence is None else f"{base}?s={sentence}"


def goals_from_scenario(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"id": g["id"], "text": g["text"], "done": False, "turn_completed": None}
        for g in scenario["goals"]
    ]


@dataclass(slots=True)
class _Transcription:
    text: str
    provider: str | None = None
    words: list[dict[str, Any]] | None = None
    no_speech_prob: float = 0.0
    duration_ms: int | None = None
    audio_key: str | None = None
    noisy: bool = False


class Orchestrator:
    def __init__(self, db: AsyncSession, router: ProviderRouter, user_id: str) -> None:
        self.db = db
        self.router = router
        self.user_id = user_id

    # ── loading ─────────────────────────────────────────────────────────────
    async def load(self, session_id: str, *, for_write: bool = False) -> PracticeSession:
        session = await self.db.scalar(
            select(PracticeSession)
            .where(PracticeSession.id == session_id)
            .options(selectinload(PracticeSession.turns))
        )
        if session is None:
            raise not_found("Session")
        if session.user_id != self.user_id:
            raise forbidden("This session belongs to another account.")
        if for_write and session.status in ("analyzing", "completed", "abandoned"):
            detail = (
                "This conversation has ended. Fetch the report instead."
                if session.status in ("analyzing", "completed")
                else "This conversation was abandoned."
            )
            raise conflict(detail)
        return session

    # ── INIT -> AI_OPENS ────────────────────────────────────────────────────
    async def start(
        self,
        scenario: dict[str, Any],
        *,
        target_turns: int,
        options: dict[str, Any],
        tts_tier: str = "premium",
    ) -> PracticeSession:
        limits = scenario["turn_limits"]
        if not limits["min"] <= target_turns <= limits["max"]:
            raise unprocessable(
                f"target_turns must be between {limits['min']} and "
                f"{limits['max']} for this scenario.",
                allowed={"min": limits["min"], "max": limits["max"], "default": limits["default"]},
            )

        # The id is assigned here rather than at INSERT time so the opening turn
        # and its TTS can be built before the first flush - assigning a
        # relationship on an already-persistent row would re-load the
        # collection, which is a lazy load in the middle of async code.
        session = PracticeSession(
            id=session_id(),
            user_id=self.user_id,
            scenario_id=scenario["id"],
            language=scenario["language"],
            level=scenario["level"],
            target_turns=target_turns,
            status="active",
            goals_state=goals_from_scenario(scenario),
            options=options,
            provider_trace={},
        )
        self.db.add(session)

        opening = scenario["opening_line"]
        turn = Turn(
            session_id=session.id,
            idx=0,
            role="ai",
            text=opening,
            translation_en=_opening_translation(scenario),
            suggested_replies=_opening_suggestions(scenario) or None,
        )
        # Authored line, identical for every learner: the cache's best case.
        spoken = await self._speak(opening, scenario, session, tts_tier=tts_tier, collect=[])
        if spoken:
            turn.audio_key = spoken[0]
            turn.audio_keys = [spoken[0]]
            turn.tts_provider = spoken[1]
            session.provider_trace = {"tts": [spoken[1]]}

        self.db.add(turn)
        session.turns = [turn]
        await self.db.flush()
        return session

    # ── USER_TURN -> AI_TURN ────────────────────────────────────────────────
    async def stream_turn(
        self,
        session: PracticeSession,
        scenario: dict[str, Any],
        *,
        text: str | None = None,
        audio: bytes | None = None,
        content_type: str = "audio/webm",
        client_transcript: str | None = None,
        response_delay_ms: int | None = None,
        tts_tier: str = "premium",
        native_lang: str = "en",
    ) -> AsyncIterator[SseEvent]:
        used = session.user_turns_used
        if used >= session.target_turns:
            raise conflict("Turn budget is already spent. End the session to get your report.")

        # ── 1. transcription ────────────────────────────────────────────────
        if audio:
            heard = await self._transcribe(
                session, scenario, audio, content_type, client_transcript
            )
            if heard is None:
                yield SseEvent(
                    "no_speech",
                    {
                        "reason": "silence",
                        "turn_consumed": False,
                        "message": "I didn't catch that. Try again?",
                    },
                )
                yield SseEvent("done", {})
                return
            yield SseEvent(
                "transcript",
                {
                    "text": heard.text,
                    "words": heard.words,
                    "provider": heard.provider,
                    "duration_ms": heard.duration_ms,
                    "noisy": heard.noisy,
                },
            )
        else:
            heard = _Transcription(text=sanitize_learner_text(text or ""))

        if not heard.text:
            raise unprocessable("Provide either `text` or an `audio` file for this turn.")

        # ── 2. record the learner's turn ────────────────────────────────────
        user_idx = len(session.turns)
        user_turn = Turn(
            session_id=session.id,
            idx=user_idx,
            role="user",
            text=heard.text,
            audio_key=heard.audio_key,
            duration_ms=heard.duration_ms,
            stt_provider=heard.provider,
            stt_words=heard.words,
            no_speech_prob=heard.no_speech_prob or None,
            response_delay_ms=response_delay_ms,
        )
        self.db.add(user_turn)
        session.turns = [*session.turns, user_turn]
        await self.db.flush()

        turn_number = used + 1
        ai_idx = user_idx + 1

        # ── 3. the single LLM call, streamed ────────────────────────────────
        messages = [
            Msg(
                "system",
                roleplay_system_prompt(
                    scenario,
                    level=session.level,
                    turn=turn_number,
                    target_turns=session.target_turns,
                    goals_state=session.goals_state,
                    summary=session.summary,
                    native_lang=native_lang,
                ),
            ),
            *self._history(session),
        ]

        chunker = StreamChunker(session.language)
        pieces: list[str] = []
        sentence_keys: list[str] = []
        tts_provider: str | None = None
        llm_provider = ""
        past_delimiter = False

        async for provider_name, delta in self.router.llm_stream(
            messages, user_id=self.user_id, temperature=0.7, max_tokens=360
        ):
            llm_provider = provider_name
            pieces.append(delta)
            if past_delimiter:
                continue

            # Everything after ###META is metadata: it must never be spoken or
            # shown as dialogue.
            _, tail = split_reply("".join(pieces))
            if tail or "###" in delta:
                past_delimiter = True
                remainder = chunker.flush()
                if remainder:
                    spoken = await self._speak(
                        remainder, scenario, session, tts_tier=tts_tier, collect=sentence_keys
                    )
                    if spoken:
                        tts_provider = spoken[1]
                        yield self._audio_event(session.id, ai_idx, len(sentence_keys) - 1)
                continue

            yield SseEvent("ai_delta", {"text": delta})
            for sentence in chunker.feed(delta):
                spoken = await self._speak(
                    sentence, scenario, session, tts_tier=tts_tier, collect=sentence_keys
                )
                if spoken:
                    tts_provider = spoken[1]
                    yield self._audio_event(session.id, ai_idx, len(sentence_keys) - 1)

        reply_text, tail = split_reply("".join(pieces))
        meta = parse_meta(tail)

        if not past_delimiter:
            remainder = chunker.flush()
            if remainder:
                spoken = await self._speak(
                    remainder, scenario, session, tts_tier=tts_tier, collect=sentence_keys
                )
                if spoken:
                    tts_provider = spoken[1]
                    yield self._audio_event(session.id, ai_idx, len(sentence_keys) - 1)

        # ── 4. language lock: one retry, then accept (§6.6) ─────────────────
        if reply_text and not langlock.is_on_target(reply_text, session.language):
            log.info("language lock tripped; regenerating once")
            retry = await self._regenerate_on_target(messages, session.language)
            if retry:
                reply_text, meta = retry
                sentence_keys.clear()
                for i, sentence in enumerate(split_sentences(reply_text, session.language)):
                    spoken = await self._speak(
                        sentence, scenario, session, tts_tier=tts_tier, collect=sentence_keys
                    )
                    if spoken:
                        tts_provider = spoken[1]
                        yield self._audio_event(session.id, ai_idx, i)
                yield SseEvent("ai_replace", {"text": reply_text, "reason": "language_lock"})

        # ── 5. persist and decide whether we are done ───────────────────────
        ai_turn = self._record_ai_turn(
            session, ai_idx, reply_text, meta, llm_provider, sentence_keys, tts_provider
        )
        self._apply_goals(session, meta, turn_number)
        ended = self._should_end(session, meta, turn_number)
        await self._finalize(session, turn_number, ended)

        yield SseEvent(
            "meta",
            {
                **meta.as_dict(),
                "goals": session.goals_state,
                "providers": {
                    "llm": llm_provider,
                    "stt": heard.provider,
                    "tts": tts_provider,
                },
            },
        )
        yield SseEvent(
            "turn_state",
            {
                "used": session.user_turns_used,
                "target": session.target_turns,
                "ended": ended,
                "status": session.status,
                "ai_turn_idx": ai_turn.idx,
            },
        )
        yield SseEvent("done", {})

    # ── helpers ─────────────────────────────────────────────────────────────
    @staticmethod
    def _audio_event(session_id: str, ai_idx: int, sentence_idx: int) -> SseEvent:
        return SseEvent(
            "ai_audio",
            {
                "sentence_idx": sentence_idx,
                "url": audio_url(session_id, ai_idx, sentence_idx),
            },
        )

    async def _transcribe(
        self,
        session: PracticeSession,
        scenario: dict[str, Any],
        audio: bytes,
        content_type: str,
        client_transcript: str | None,
    ) -> _Transcription | None:
        if len(audio) > settings.max_audio_bytes:
            raise audio_too_large(settings.max_audio_bytes)
        # 1.5x slack: the byte-length estimate is rough, and rejecting a valid
        # 25 s turn would be worse than transcribing a 40 s one.
        if estimate_duration_s(audio, content_type) > settings.max_audio_seconds * 1.5:
            raise unprocessable(f"Audio is too long (max {settings.max_audio_seconds}s per turn).")

        rms = peak_rms(audio)
        result = await self.router.transcribe(
            audio,
            lang=session.language,
            prompt=" ".join(scenario.get("target_vocab") or [])[:400],
            content_type=content_type,
            client_transcript=client_transcript,
            user_id=self.user_id,
        )
        if result.no_speech_prob >= NO_SPEECH_THRESHOLD or not result.text.strip():
            return None

        audio_key: str | None = None
        if settings.audio_retention_days > 0 and session.options.get("keep_audio"):
            audio_key = turn_audio_key(session.id, len(session.turns), "user")
            await get_storage().put(audio_key, audio, content_type)

        return _Transcription(
            text=sanitize_learner_text(result.text),
            provider=result.provider,
            words=[
                {"w": w.w, "start": w.start, "end": w.end, "prob": w.prob} for w in result.words
            ],
            no_speech_prob=result.no_speech_prob,
            duration_ms=int(result.duration_s * 1000) or None,
            audio_key=audio_key,
            noisy=bool(rms is not None and rms < NOISY_RMS),
        )

    async def _speak(
        self,
        sentence: str,
        scenario: dict[str, Any],
        session: PracticeSession,
        *,
        tts_tier: str,
        collect: list[str],
    ) -> tuple[str, str] | None:
        """Synthesize one sentence, appending its key to `collect`.

        Returns `(storage_key, provider)`, or None when the client should speak
        the line itself.  TTS failure is never fatal: the browser voice is the
        always-on fallback (§7.4).
        """
        try:
            result = await speech.synthesize(
                self.db,
                self.router,
                sentence,
                lang=session.language,
                voice=(scenario.get("voice") or {}).get("azure"),
                rate=float(session.options.get("tts_rate") or 1.0),
                user_id=self.user_id,
                tier=tts_tier,
            )
        except Exception:
            log.warning("TTS failed for a sentence; client falls back", exc_info=True)
            return None
        if not result:
            return None
        chunk, key = result
        collect.append(key)
        return key, chunk.provider

    def _history(self, session: PracticeSession) -> list[Msg]:
        recent = sorted(session.turns, key=lambda t: t.idx)[-HISTORY_WINDOW:]
        return [
            Msg("assistant" if t.role == "ai" else "user", t.text) for t in recent if t.text.strip()
        ]

    async def _regenerate_on_target(
        self, messages: list[Msg], lang: str
    ) -> tuple[str, TurnMeta] | None:
        name = LANGUAGE_NAMES.get(lang, lang)
        stricter = [
            *messages,
            Msg(
                "system",
                f"Your previous reply was not in {name}. Reply again, entirely in {name}, "
                "using exactly the same output format.",
            ),
        ]
        try:
            _, raw = await self.router.llm_complete(
                stricter, user_id=self.user_id, temperature=0.5, max_tokens=360
            )
        except Exception:
            return None
        reply, tail = split_reply(raw)
        return (reply, parse_meta(tail)) if reply and langlock.is_on_target(reply, lang) else None

    def _record_ai_turn(
        self,
        session: PracticeSession,
        idx: int,
        reply_text: str,
        meta: TurnMeta,
        llm_provider: str,
        audio_keys: list[str],
        tts_provider: str | None,
    ) -> Turn:
        turn = Turn(
            session_id=session.id,
            idx=idx,
            role="ai",
            text=reply_text,
            translation_en=meta.translation_en or None,
            romanization=meta.romanization or None,
            suggested_replies=meta.suggested_replies or None,
            llm_provider=llm_provider,
            tts_provider=tts_provider,
            audio_key=audio_keys[0] if audio_keys else None,
            audio_keys=list(audio_keys) or None,
        )
        self.db.add(turn)
        session.turns = [*session.turns, turn]

        trace = {k: list(v) for k, v in (session.provider_trace or {}).items()}
        for capability, name in (("llm", llm_provider), ("tts", tts_provider)):
            if name and name not in trace.setdefault(capability, []):
                trace[capability].append(name)
        session.provider_trace = trace
        return turn

    def _apply_goals(self, session: PracticeSession, meta: TurnMeta, turn_number: int) -> None:
        """Goal completion is monotonic — the model cannot un-achieve a goal."""
        done = set(meta.goals_done)
        session.goals_state = [
            {**goal, "done": True, "turn_completed": turn_number}
            if not goal.get("done") and goal["id"] in done
            else dict(goal)
            for goal in session.goals_state
        ]

    def _should_end(self, session: PracticeSession, meta: TurnMeta, turn_number: int) -> bool:
        if turn_number >= session.target_turns:
            return True
        all_done = bool(session.goals_state) and all(g.get("done") for g in session.goals_state)
        return bool(meta.end and all_done and turn_number >= MIN_TURNS_BEFORE_END)

    async def _finalize(self, session: PracticeSession, turn_number: int, ended: bool) -> None:
        if ended:
            session.status = "analyzing"
            session.ended_at = dt.datetime.now(dt.UTC)
        elif turn_number > HISTORY_WINDOW and turn_number % SUMMARY_EVERY == 0:
            await self._refresh_summary(session)
        await self.db.flush()

    async def _refresh_summary(self, session: PracticeSession) -> None:
        """Compress the turns that are about to fall out of the prompt window."""
        transcript = "\n".join(
            f"{'character' if t.role == 'ai' else 'learner'}: {t.text}"
            for t in sorted(session.turns, key=lambda t: t.idx)
        )
        try:
            _, text = await self.router.llm_complete(
                [Msg("system", summary_system_prompt(session.language)), Msg("user", transcript)],
                user_id=self.user_id,
                temperature=0.1,
                max_tokens=160,
            )
        except Exception:
            log.warning("summary refresh failed; keeping the previous summary", exc_info=True)
            return
        if text.strip():
            session.summary = text.strip()[:600]

    # ── assist tools (§6.5) ─────────────────────────────────────────────────
    async def explain(
        self, *, lang: str, level: str, target: str, context: str = "", native_lang: str = "en"
    ) -> dict[str, Any]:
        _, raw = await self.router.llm_complete(
            [
                Msg("system", explain_system_prompt(lang, level=level, native_lang=native_lang)),
                Msg(
                    "user",
                    f"Term: {sanitize_learner_text(target, max_len=120)}\n"
                    f"Sentence it appeared in: {sanitize_learner_text(context, max_len=300)}",
                ),
            ],
            user_id=self.user_id,
            temperature=0.2,
            max_tokens=400,
            json_mode=True,
        )
        return parse_json_object(raw) or {
            "term": target,
            "meaning": "Explanation unavailable right now. Try again in a moment.",
        }

    # ── CLOSING ─────────────────────────────────────────────────────────────
    async def end(self, session: PracticeSession) -> PracticeSession:
        if session.status in ("completed", "analyzing"):
            return session
        if session.user_turns_used < MIN_TURNS_BEFORE_END:
            raise conflict(
                f"Talk for at least {MIN_TURNS_BEFORE_END} turns before ending "
                f"(you are at {session.user_turns_used})."
            )
        session.status = "analyzing"
        session.ended_at = dt.datetime.now(dt.UTC)
        await self.db.flush()
        return session

    async def abandon(self, session: PracticeSession) -> None:
        session.status = "abandoned"
        session.ended_at = dt.datetime.now(dt.UTC)
        await self.db.flush()


def _opening_translation(scenario: dict[str, Any]) -> str | None:
    """The authored opening line has no model translation, so reuse the phrase
    list when it contains the same line; otherwise leave it for the client's
    translate button."""
    for phrase in scenario.get("useful_phrases") or []:
        if phrase.get("text") == scenario["opening_line"]:
            return phrase.get("meaning")
    return None


def _opening_suggestions(scenario: dict[str, Any]) -> list[str]:
    return [p["text"] for p in (scenario.get("useful_phrases") or [])[:3]]

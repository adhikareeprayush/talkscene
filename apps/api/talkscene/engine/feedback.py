"""The end-of-conversation report (plan §8).

Division of labour, which is the whole design:

| Section            | Computed by            |
|--------------------|------------------------|
| Goal completion    | the orchestrator's state (authoritative) |
| Speaking & fluency | `engine/fluency.py` — arithmetic over word timings |
| Register           | `engine/register.py` — morphology heuristics |
| Grammar & vocab    | the LLM, in JSON mode  |
| Pronunciation      | STT confidence, labelled **estimated**, plus drills |
| Overall score      | the weighted rubric below, from those parts |

The LLM is never asked for a number it cannot know.  It never scores
pronunciation (it is reading a transcript) and it is handed the measured
fluency figures with an instruction not to contradict them.

Scoring (§8.3):

    Overall = 0.30*task + 0.25*grammar + 0.20*fluency + 0.15*pronunciation
            + 0.10*vocabulary

Every sub-score is returned with the evidence behind it, so the UI can explain
the number instead of just showing it.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.report import Report
from ..models.scenario import Scenario
from ..models.session import PracticeSession
from ..models.user import User
from ..models.vocab import VocabItem
from ..providers.base import Msg
from ..providers.router import ProviderRouter
from . import drills as drill_builder
from . import fluency as fluency_mod
from . import register as register_mod
from .meta import parse_json_object
from .prompts import PRONUNCIATION_FOCUS, feedback_system_prompt, feedback_user_prompt

log = logging.getLogger("talkscene.feedback")

WEIGHTS = {
    "task_completion": 0.30,
    "grammar": 0.25,
    "fluency": 0.20,
    "pronunciation": 0.15,
    "vocabulary": 0.10,
}

CEFR_LADDER = ("A1", "A1+", "A2", "A2+", "B1", "B1+", "B2", "B2+", "C1")
MAX_AUTO_FLASHCARDS = 3


def _clamp(value: Any, default: float = 60.0) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return default


def task_score(goals_state: list[dict[str, Any]]) -> tuple[float, int, int]:
    total = len(goals_state)
    done = sum(1 for g in goals_state if g.get("done"))
    return (100.0 * done / total if total else 0.0), done, total


def pronunciation_estimate(fluency: fluency_mod.FluencyReport) -> tuple[float, str]:
    """A clarity *estimate* from STT confidence — explicitly not a PA score.

    Returns `(score, basis)`.  With no timings at all (a text-only session) the
    honest answer is "unknown", and the overall score re-weights instead of
    inventing a value.
    """
    if fluency.estimated_from_text or fluency.word_count == 0:
        return 0.0, "unavailable"
    unclear = len(fluency.unclear_words)
    ratio = unclear / max(fluency.word_count, 1)
    return round(max(40.0, 100.0 - ratio * 220), 1), "stt_confidence"


def weighted_overall(parts: dict[str, float], *, skip: set[str]) -> int:
    """Weighted mean over the sub-scores we actually have, renormalised."""
    usable = {k: v for k, v in parts.items() if k not in skip}
    total_weight = sum(WEIGHTS[k] for k in usable) or 1.0
    return round(sum(parts[k] * WEIGHTS[k] for k in usable) / total_weight)


def estimate_cefr(level: str, overall: int) -> str:
    """Nudge the learner's own level by performance, never more than one step."""
    base = level.upper()[:2]
    try:
        i = CEFR_LADDER.index(base)
    except ValueError:
        return base
    if overall >= 85:
        return CEFR_LADDER[min(i + 1, len(CEFR_LADDER) - 1)]
    if overall < 50:
        return CEFR_LADDER[max(i - 1, 0)]
    return f"{base}+" if overall >= 70 else base


async def _recommend_next(
    db: AsyncSession, session: PracticeSession, suggested: str | None
) -> str | None:
    """Prefer the model's suggestion when it is a real published scenario, else
    pick an unplayed one in the same language and level but a new category."""
    if suggested:
        row = await db.get(Scenario, suggested)
        if row is not None and row.is_published and row.language == session.language:
            return row.id

    played = select(PracticeSession.scenario_id).where(PracticeSession.user_id == session.user_id)
    current = await db.get(Scenario, session.scenario_id)
    stmt = (
        select(Scenario.id)
        .where(
            Scenario.language == session.language,
            Scenario.level == session.level,
            Scenario.is_published.is_(True),
            Scenario.id.not_in(played),
        )
        .order_by(Scenario.category != (current.category if current else ""), Scenario.id)
        .limit(1)
    )
    return await db.scalar(stmt)


async def _create_flashcards(
    db: AsyncSession, session: PracticeSession, suggestions: list[Any], *, is_guest: bool
) -> list[dict[str, Any]]:
    """Auto-create up to three cards from the report's vocabulary suggestions.

    The example sentence comes from *this* conversation where possible — a card
    the learner has a memory of is a card they will actually recall.
    """
    from ..learning import fsrs

    # Guests cannot reach /v1/vocab, so creating cards for them would be
    # invisible work. The report tells them to sign up instead.
    if is_guest:
        return []

    created: list[dict[str, Any]] = []
    for raw in suggestions[:MAX_AUTO_FLASHCARDS]:
        item = raw if isinstance(raw, dict) else {"term": str(raw)}
        term = (item.get("term") or "").strip()
        if not term:
            continue
        exists = await db.scalar(
            select(func.count())
            .select_from(VocabItem)
            .where(
                VocabItem.user_id == session.user_id,
                VocabItem.language == session.language,
                VocabItem.term == term,
            )
        )
        if exists:
            continue
        example = item.get("example") or next(
            (t.text for t in session.turns if term in (t.text or "")), None
        )
        vocab = VocabItem(
            user_id=session.user_id,
            language=session.language,
            term=term,
            reading=(item.get("reading") or "").strip() or None,
            meaning=(item.get("meaning") or "").strip() or "—",
            example=example,
            source_session_id=session.id,
        )
        db.add(vocab)
        await db.flush()
        db.add(fsrs.new_card(vocab.id, session.user_id))
        created.append({"id": vocab.id, "term": term, "meaning": vocab.meaning})
    return created


async def generate(
    db: AsyncSession,
    router: ProviderRouter,
    session: PracticeSession,
    scenario: dict[str, Any],
) -> Report:
    """Build and persist the report. Idempotent: an existing report is returned."""
    existing = await db.scalar(select(Report).where(Report.session_id == session.id))
    if existing is not None:
        return existing

    turns = sorted(session.turns, key=lambda t: t.idx)
    transcript = [
        {"idx": t.idx, "role": t.role, "text": t.text, "translation_en": t.translation_en}
        for t in turns
    ]
    learner_turns = [
        {
            "idx": t.idx,
            "text": t.text,
            "words": t.stt_words or [],
            "duration_ms": t.duration_ms,
            "response_delay_ms": t.response_delay_ms,
        }
        for t in turns
        if t.role == "user"
    ]
    ai_lines = [t.text for t in turns if t.role == "ai" and t.text]

    # ── measured, not asked for ─────────────────────────────────────────────
    fluency = fluency_mod.analyze(learner_turns, lang=session.language)
    fluency_value = fluency_mod.fluency_score(fluency, level=session.level)
    register = register_mod.lint(
        learner_turns,
        lang=session.language,
        persona_style=scenario["persona"]["style"],
        category=scenario.get("category", ""),
        expected=scenario.get("learner_register"),
    )
    task_value, goals_done, goals_total = task_score(session.goals_state)
    pron_value, pron_basis = pronunciation_estimate(fluency)

    # ── the one LLM call ────────────────────────────────────────────────────
    llm: dict[str, Any] = {}
    llm_provider = ""
    try:
        llm_provider, raw = await router.llm_complete(
            [
                Msg("system", feedback_system_prompt(scenario, level=session.level)),
                Msg(
                    "user",
                    feedback_user_prompt(
                        transcript, goals_state=session.goals_state, fluency=fluency.as_dict()
                    ),
                ),
            ],
            user_id=session.user_id,
            temperature=0.2,
            max_tokens=1600,
            json_mode=True,
        )
        llm = parse_json_object(raw) or {}
    except Exception:
        log.exception("feedback LLM call failed; falling back to measured sections only")

    grammar_value = _clamp(llm.get("grammar_score"), 62.0)
    vocab_value = _clamp(llm.get("vocabulary_score"), 62.0)
    # The orchestrator's goal state wins over the model's opinion of it.
    if llm.get("task_completion_score") is not None and goals_total == 0:
        task_value = _clamp(llm["task_completion_score"])

    parts = {
        "task_completion": task_value,
        "grammar": grammar_value,
        "fluency": fluency_value,
        "pronunciation": pron_value,
        "vocabulary": vocab_value,
    }
    skip = {"pronunciation"} if pron_basis == "unavailable" else set()
    overall = weighted_overall(parts, skip=skip)
    cefr = llm.get("estimated_cefr") or estimate_cefr(session.level, overall)
    if cefr not in CEFR_LADDER:
        cefr = estimate_cefr(session.level, overall)

    # ── follow-ups the learner can act on ───────────────────────────────────
    drill_plan = drill_builder.select_sentences(
        scenario=scenario, ai_lines=ai_lines, fluency=fluency
    )
    created_drills = await drill_builder.create(
        db,
        user_id=session.user_id,
        session_id=session.id,
        language=session.language,
        sentences=drill_plan,
    )
    learner = await db.get(User, session.user_id)
    is_guest = bool(learner and learner.is_guest)
    flashcards = await _create_flashcards(
        db, session, (llm.get("vocab") or {}).get("suggested") or [], is_guest=is_guest
    )
    next_scenario = await _recommend_next(db, session, llm.get("next_scenario_id"))

    payload: dict[str, Any] = {
        "session_id": session.id,
        "scenario_id": session.scenario_id,
        "language": session.language,
        "level": session.level,
        "overall": overall,
        "estimated_cefr": cefr,
        "summary": (llm.get("overall_impression") or "").strip()
        or _fallback_summary(goals_done, goals_total, fluency),
        "scores": {
            "task_completion": round(parts["task_completion"], 1),
            "grammar": round(parts["grammar"], 1),
            "fluency": round(parts["fluency"], 1),
            # null rather than 0: a text-only session has nothing to estimate
            # pronunciation from, and a zero would read as a bad score.
            "pronunciation": None
            if pron_basis == "unavailable"
            else round(parts["pronunciation"], 1),
            "vocabulary": round(parts["vocabulary"], 1),
            "weights": WEIGHTS,
            "pronunciation_basis": pron_basis,
            "excluded_from_overall": sorted(skip),
        },
        "goals": {
            "done": goals_done,
            "total": goals_total,
            "items": session.goals_state,
        },
        "speaking": fluency.as_dict(),
        "grammar": {
            "corrections": _clean_corrections(llm.get("corrections")),
            "note": None if llm else "Automatic grammar review was unavailable for this session.",
        },
        "vocabulary": {
            "used_well": _strings((llm.get("vocab") or {}).get("used_well")),
            "new": _strings((llm.get("vocab") or {}).get("new")),
            "suggested": (llm.get("vocab") or {}).get("suggested") or [],
            "target_hit_rate": _target_hit_rate(scenario, learner_turns),
            "flashcards_created": flashcards,
            "requires_account": is_guest,
        },
        "pronunciation": {
            # Labelled, deliberately: this is STT confidence, not phoneme scoring.
            "confidence": "estimated",
            "basis": pron_basis,
            "unclear_words": [
                {"word": u.word, "turn_idx": u.turn_idx, "probability": u.probability}
                for u in fluency.unclear_words
            ],
            "focus_areas": PRONUNCIATION_FOCUS.get(session.language, ""),
            "disclaimer": (
                "These are estimates from speech-recognition confidence. "
                "Run the shadowing drills for a real pronunciation score."
            ),
            "drills": [
                {
                    "id": d.id,
                    "ref_text": d.ref_text,
                    "translation_en": d.translation_en,
                    "focus_words": d.focus_words or [],
                }
                for d in created_drills
            ],
        },
        "register": register.as_dict(),
        "native_language_turns": int(
            llm.get("native_language_turns") or fluency.native_language_turns
        ),
        "next_steps": {
            "focus": (llm.get("next_focus") or "").strip() or None,
            "next_scenario_id": next_scenario,
            "retry_scenario_id": session.scenario_id,
        },
        "transcript": transcript,
        "providers": {"llm": llm_provider or None, **(session.provider_trace or {})},
    }

    report = Report(session_id=session.id, overall=overall, estimated_cefr=cefr, json=payload)
    db.add(report)
    session.status = "completed"
    await db.flush()
    return report


def _strings(value: Any, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value[:limit] if str(v).strip()]


def _clean_corrections(value: Any, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        said = str(item.get("said") or "").strip()
        better = str(item.get("better") or "").strip()
        if not said or not better:
            continue
        out.append(
            {
                "turn": int(item["turn"]) if str(item.get("turn", "")).isdigit() else None,
                "said": said[:300],
                "better": better[:300],
                "why": str(item.get("why") or "").strip()[:400],
                "category": str(item.get("category") or "grammar").strip()[:24],
            }
        )
    return out


def _target_hit_rate(
    scenario: dict[str, Any], learner_turns: list[dict[str, Any]]
) -> dict[str, Any]:
    targets = scenario.get("target_vocab") or []
    if not targets:
        return {"used": [], "missed": [], "rate": None}
    blob = " ".join(t["text"] or "" for t in learner_turns)
    used = [w for w in targets if w and w in blob]
    return {
        "used": used,
        "missed": [w for w in targets if w not in used],
        "rate": round(len(used) / len(targets), 2),
    }


def _fallback_summary(done: int, total: int, fluency: fluency_mod.FluencyReport) -> str:
    """Used when the model's summary is unavailable. Says only what was measured."""
    goals = f"You completed {done} of {total} goals."
    if fluency.estimated_from_text:
        # A typed session has no pace or pauses to speak of.
        return f"{goals} Try the next one out loud to get feedback on your speaking too."
    pauses = len(fluency.long_pauses)
    pause_text = (
        "no long pauses" if pauses == 0 else f"{pauses} long pause{'s' if pauses != 1 else ''}"
    )
    pace = {
        "steady": "Your pace was steady",
        "hesitant": "Your pace was careful",
        "fast": "You spoke quickly",
        "unknown": "You kept the conversation going",
    }[fluency.rate_label]
    return f"{goals} {pace}, with {pause_text}. The next session builds on this one."

"""FSRS-4.5 spaced repetition (plan §2.2, §11.3 I).

FSRS rather than SM-2 because it models stability and difficulty separately,
which matters for vocabulary from conversations: a word the learner *used*
successfully behaves very differently from one they only heard.

This is the published FSRS-4.5 formulation with its default weights.  The
weights are the one thing here worth revisiting — they can be optimised per
user from review history once there is enough of it, which is why they are a
module constant and every function takes them as an argument.

Ratings: 1 = Again, 2 = Hard, 3 = Good, 4 = Easy.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Literal

from ..core.ids import card_id
from ..models.vocab import SrsCard

Rating = Literal[1, 2, 3, 4]
AGAIN: Rating = 1
HARD: Rating = 2
GOOD: Rating = 3
EASY: Rating = 4

# FSRS-4.5 default weights.
W: tuple[float, ...] = (
    0.4872,
    1.4003,
    3.7145,
    13.8206,
    5.1618,
    1.2298,
    0.8975,
    0.0310,
    1.6474,
    0.1367,
    1.0461,
    2.1072,
    0.0793,
    0.3246,
    1.5870,
    0.2272,
    2.8755,
)

DECAY = -0.5
FACTOR = 19.0 / 81.0  # = 0.9 ** (1 / DECAY) - 1
DEFAULT_RETENTION = 0.90
MIN_DIFFICULTY, MAX_DIFFICULTY = 1.0, 10.0
MIN_STABILITY = 0.1
MAX_INTERVAL_DAYS = 365 * 5

STATE_NEW = "new"
STATE_LEARNING = "learning"
STATE_REVIEW = "review"
STATE_RELEARNING = "relearning"

# Minutes, not days, for the same-session steps.
LEARNING_STEPS_MIN = {AGAIN: 1, HARD: 5, GOOD: 10, EASY: None}
RELEARNING_STEP_MIN = 10


def retrievability(elapsed_days: float, stability: float) -> float:
    """Probability of recall after `elapsed_days` at the given stability."""
    if stability <= 0:
        return 0.0
    return (1 + FACTOR * max(elapsed_days, 0.0) / stability) ** DECAY


def interval_for(stability: float, retention: float = DEFAULT_RETENTION) -> float:
    """Days until recall probability falls to `retention`."""
    retention = min(max(retention, 0.70), 0.99)
    return (stability / FACTOR) * (retention ** (1 / DECAY) - 1)


def initial_stability(rating: Rating, w: tuple[float, ...] = W) -> float:
    return max(w[rating - 1], MIN_STABILITY)


def initial_difficulty(rating: Rating, w: tuple[float, ...] = W) -> float:
    d = w[4] - math.exp(w[5] * (rating - 1)) + 1
    return _clamp_difficulty(d)


def _clamp_difficulty(d: float) -> float:
    return min(max(d, MIN_DIFFICULTY), MAX_DIFFICULTY)


def next_difficulty(difficulty: float, rating: Rating, w: tuple[float, ...] = W) -> float:
    delta = difficulty - w[6] * (rating - 3)
    # Mean reversion toward the difficulty of an "Easy" first answer.
    reverted = w[7] * initial_difficulty(EASY, w) + (1 - w[7]) * delta
    return _clamp_difficulty(reverted)


def stability_after_recall(
    stability: float, difficulty: float, r: float, rating: Rating, w: tuple[float, ...] = W
) -> float:
    hard_penalty = w[15] if rating == HARD else 1.0
    easy_bonus = w[16] if rating == EASY else 1.0
    growth = (
        math.exp(w[8])
        * (11 - difficulty)
        * (stability ** -w[9])
        * (math.exp(w[10] * (1 - r)) - 1)
        * hard_penalty
        * easy_bonus
    ) + 1
    return max(stability * growth, MIN_STABILITY)


def stability_after_forget(
    stability: float, difficulty: float, r: float, w: tuple[float, ...] = W
) -> float:
    forgotten = (
        w[11] * (difficulty ** -w[12]) * ((stability + 1) ** w[13] - 1) * math.exp(w[14] * (1 - r))
    )
    # FSRS-4.5: a lapse can never *increase* stability.
    return max(min(forgotten, stability), MIN_STABILITY)


def new_card(vocab_item_id: str, user_id: str, *, now: dt.datetime | None = None) -> SrsCard:
    moment = now or dt.datetime.now(dt.UTC)
    return SrsCard(
        id=card_id(),
        vocab_item_id=vocab_item_id,
        user_id=user_id,
        due_at=moment,
        stability=0.0,
        difficulty=0.0,
        reps=0,
        lapses=0,
        state=STATE_NEW,
        scheduled_days=0,
    )


def review(
    card: SrsCard,
    rating: Rating,
    *,
    now: dt.datetime | None = None,
    retention: float = DEFAULT_RETENTION,
    w: tuple[float, ...] = W,
) -> SrsCard:
    """Apply one review in place and return the card."""
    if rating not in (AGAIN, HARD, GOOD, EASY):
        raise ValueError(f"rating must be 1-4, got {rating!r}")
    moment = now or dt.datetime.now(dt.UTC)

    if card.state == STATE_NEW:
        card.stability = initial_stability(rating, w)
        card.difficulty = initial_difficulty(rating, w)
        card.state = STATE_REVIEW if rating == EASY else STATE_LEARNING
    else:
        last = card.last_reviewed_at or moment
        if last.tzinfo is None:
            last = last.replace(tzinfo=dt.UTC)
        elapsed = max((moment - last).total_seconds() / 86400.0, 0.0)
        r = retrievability(elapsed, card.stability or MIN_STABILITY)

        card.difficulty = next_difficulty(card.difficulty or initial_difficulty(GOOD, w), rating, w)
        if rating == AGAIN:
            card.stability = stability_after_forget(card.stability, card.difficulty, r, w)
            card.lapses += 1
            card.state = STATE_RELEARNING
        else:
            card.stability = stability_after_recall(card.stability, card.difficulty, r, rating, w)
            card.state = STATE_REVIEW

    card.reps += 1
    card.last_reviewed_at = moment

    # Learning and relearning cards come back inside the same session.
    step_minutes = None
    if card.state in (STATE_LEARNING, STATE_RELEARNING):
        step_minutes = (
            RELEARNING_STEP_MIN if card.state == STATE_RELEARNING else LEARNING_STEPS_MIN[rating]
        )

    if step_minutes:
        card.scheduled_days = 0
        card.due_at = moment + dt.timedelta(minutes=step_minutes)
    else:
        days = max(1, round(min(interval_for(card.stability, retention), MAX_INTERVAL_DAYS)))
        card.scheduled_days = days
        card.due_at = moment + dt.timedelta(days=days)
        card.state = STATE_REVIEW
    return card


def preview(
    card: SrsCard, *, now: dt.datetime | None = None, retention: float = DEFAULT_RETENTION
) -> dict[str, str]:
    """What each button would schedule — shown on the flashcard buttons."""
    out: dict[str, str] = {}
    for rating, label in ((AGAIN, "again"), (HARD, "hard"), (GOOD, "good"), (EASY, "easy")):
        clone = SrsCard(
            id=card.id,
            vocab_item_id=card.vocab_item_id,
            user_id=card.user_id,
            due_at=card.due_at,
            last_reviewed_at=card.last_reviewed_at,
            stability=card.stability,
            difficulty=card.difficulty,
            reps=card.reps,
            lapses=card.lapses,
            state=card.state,
            scheduled_days=card.scheduled_days,
        )
        review(clone, rating, now=now, retention=retention)  # type: ignore[arg-type]
        if clone.scheduled_days:
            out[label] = f"{clone.scheduled_days}d"
        else:
            minutes = (clone.due_at - (now or dt.datetime.now(dt.UTC))).total_seconds() // 60
            out[label] = f"{max(1, int(minutes))}m"
    return out

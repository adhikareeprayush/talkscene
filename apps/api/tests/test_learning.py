"""FSRS scheduling, vocabulary, drills and progress."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
from conftest import events_named, run_turn, start_session, wav_bytes

from talkscene.learning import fsrs
from talkscene.models.vocab import SrsCard


def new_card() -> SrsCard:
    return fsrs.new_card("voc_test", "usr_test", now=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))


# ── FSRS ────────────────────────────────────────────────────────────────────
def test_a_new_card_is_due_immediately() -> None:
    card = new_card()
    assert card.state == "new"
    assert card.reps == 0
    assert card.due_at == dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@pytest.mark.parametrize("rating", [1, 2, 3, 4])
def test_the_first_answer_sets_stability_and_difficulty(rating: int) -> None:
    card = new_card()
    fsrs.review(card, rating, now=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    assert card.reps == 1
    assert card.stability > 0
    assert fsrs.MIN_DIFFICULTY <= card.difficulty <= fsrs.MAX_DIFFICULTY


def test_better_answers_schedule_further_out() -> None:
    intervals = {}
    for rating in (1, 2, 3, 4):
        card = new_card()
        fsrs.review(card, rating, now=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
        intervals[rating] = card.due_at
    assert intervals[1] < intervals[2] < intervals[3] < intervals[4]


def test_again_on_a_learning_card_returns_it_within_the_session() -> None:
    card = new_card()
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    fsrs.review(card, 1, now=now)
    assert card.state == "learning"
    assert card.scheduled_days == 0
    assert (card.due_at - now) < dt.timedelta(hours=1)


def test_a_lapse_never_increases_stability() -> None:
    card = new_card()
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    fsrs.review(card, 4, now=now)  # Easy -> review state
    mature = card.stability
    fsrs.review(card, 1, now=now + dt.timedelta(days=30))
    assert card.stability <= mature
    assert card.lapses == 1
    assert card.state == "relearning"


def test_repeated_good_answers_grow_the_interval() -> None:
    card = new_card()
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    gaps: list[int] = []
    for _ in range(5):
        fsrs.review(card, 3, now=now)
        now = card.due_at
        gaps.append(card.scheduled_days)
    graduated = [g for g in gaps if g > 0]
    assert graduated == sorted(graduated)
    assert graduated[-1] > graduated[0]


def test_retrievability_decays_with_time() -> None:
    assert fsrs.retrievability(0, 10) == pytest.approx(1.0)
    assert fsrs.retrievability(10, 10) == pytest.approx(0.9, abs=0.01)
    assert fsrs.retrievability(100, 10) < 0.6


def test_interval_matches_the_requested_retention() -> None:
    at_90 = fsrs.interval_for(10.0, 0.90)
    at_95 = fsrs.interval_for(10.0, 0.95)
    assert at_90 == pytest.approx(10.0, abs=0.01)
    assert at_95 < at_90, "wanting to remember more means reviewing sooner"


def test_an_invalid_rating_is_refused() -> None:
    with pytest.raises(ValueError):
        fsrs.review(new_card(), 5)  # type: ignore[arg-type]


def test_preview_describes_every_button_without_mutating_the_card() -> None:
    card = new_card()
    before = (card.reps, card.stability, card.due_at)
    preview = fsrs.preview(card, now=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    assert set(preview) == {"again", "hard", "good", "easy"}
    assert (card.reps, card.stability, card.due_at) == before


# ── vocabulary API ──────────────────────────────────────────────────────────
async def test_saving_a_word_creates_a_due_card(client: httpx.AsyncClient, account: dict) -> None:
    response = await client.post(
        "/v1/vocab",
        headers=account,
        json={
            "language": "ko",
            "term": "조식",
            "meaning": "breakfast",
            "example": "조식은 몇 시예요?",
        },
    )
    assert response.status_code == 201
    assert response.json()["state"] == "new"

    due = await client.get("/v1/srs/due", headers=account)
    assert due.status_code == 200
    assert len(due.json()) == 1
    card = due.json()[0]
    assert card["vocab"]["term"] == "조식"
    assert set(card["intervals"]) == {"again", "hard", "good", "easy"}


async def test_saving_the_same_word_twice_is_idempotent(
    client: httpx.AsyncClient, account: dict
) -> None:
    payload = {"language": "ja", "term": "お通し", "meaning": "compulsory small dish"}
    first = await client.post("/v1/vocab", headers=account, json=payload)
    second = await client.post("/v1/vocab", headers=account, json=payload)
    assert first.json()["id"] == second.json()["id"]
    assert (await client.get("/v1/vocab", headers=account)).json()["total"] == 1


async def test_reviewing_reschedules_and_reports_what_is_left(
    client: httpx.AsyncClient, account: dict
) -> None:
    await client.post(
        "/v1/vocab",
        headers=account,
        json={"language": "de", "term": "Kaution", "meaning": "deposit"},
    )
    card = (await client.get("/v1/srs/due", headers=account)).json()[0]

    response = await client.post(
        f"/v1/srs/{card['card_id']}/review", headers=account, json={"rating": 4}
    )
    assert response.status_code == 200
    assert response.json()["scheduled_days"] >= 1
    assert response.json()["remaining_due"] == 0
    assert (await client.get("/v1/srs/due", headers=account)).json() == []


async def test_a_double_tap_on_the_answer_button_is_refused(
    client: httpx.AsyncClient, account: dict
) -> None:
    await client.post(
        "/v1/vocab", headers=account, json={"language": "en", "term": "faulty", "meaning": "broken"}
    )
    card = (await client.get("/v1/srs/due", headers=account)).json()[0]
    await client.post(f"/v1/srs/{card['card_id']}/review", headers=account, json={"rating": 3})
    again = await client.post(
        f"/v1/srs/{card['card_id']}/review", headers=account, json={"rating": 3}
    )
    assert again.status_code == 409


async def test_vocabulary_requires_an_account(client: httpx.AsyncClient, guest: dict) -> None:
    response = await client.post(
        "/v1/vocab", headers=guest, json={"language": "ko", "term": "조식", "meaning": "breakfast"}
    )
    assert response.status_code == 403
    assert "account" in response.json()["detail"]


async def test_cards_belong_to_their_owner(client: httpx.AsyncClient, account: dict) -> None:
    await client.post(
        "/v1/vocab",
        headers=account,
        json={"language": "ko", "term": "예약", "meaning": "reservation"},
    )
    card = (await client.get("/v1/srs/due", headers=account)).json()[0]

    other = await client.post(
        "/v1/auth/signup", json={"email": "other@example.com", "password": "another-long-password"}
    )
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert (await client.get("/v1/srs/due", headers=headers)).json() == []
    response = await client.post(
        f"/v1/srs/{card['card_id']}/review", headers=headers, json={"rating": 3}
    )
    assert response.status_code == 403


# ── drills ──────────────────────────────────────────────────────────────────
async def _session_with_voice(client: httpx.AsyncClient, headers: dict) -> str:
    session = await start_session(client, headers, "ja-konbini-a1", target_turns=6, input="voice")
    sid = session["session_id"]
    for _ in range(6):
        response = await client.post(
            f"/v1/sessions/{sid}/turns",
            headers=headers,
            files={"audio": ("t.wav", wav_bytes(2.0), "audio/wav")},
            data={"client_transcript": "おにぎりはどこですか"},
        )
        if events_named(response.text, "turn_state")[0]["ended"]:
            break
    await client.get(f"/v1/sessions/{sid}/report", headers=headers, params={"wait": "true"})
    return sid


async def test_drill_set_is_reused_rather_than_duplicated(
    client: httpx.AsyncClient, account: dict
) -> None:
    sid = await _session_with_voice(client, account)
    first = await client.post("/v1/drills", headers=account, json={"session_id": sid})
    second = await client.post("/v1/drills", headers=account, json={"session_id": sid})
    assert first.status_code == second.status_code == 201
    assert [d["id"] for d in first.json()["drills"]] == [d["id"] for d in second.json()["drills"]]


async def test_an_attempt_is_scored_and_marked_non_authoritative_without_azure(
    client: httpx.AsyncClient, account: dict
) -> None:
    """Without Azure PA there is no phoneme data, and the response must say so
    rather than present an estimate as a measurement (ADR 0003)."""
    sid = await _session_with_voice(client, account)
    drill = (await client.post("/v1/drills", headers=account, json={"session_id": sid})).json()[
        "drills"
    ][0]

    response = await client.post(
        f"/v1/drills/{drill['id']}/attempts",
        headers=account,
        files={"audio": ("a.wav", wav_bytes(2.0), "audio/wav")},
    )
    assert response.status_code == 201
    attempt = response.json()
    assert attempt["provider"] == "heuristic"
    assert attempt["authoritative"] is False
    assert all(word["phonemes"] == [] for word in attempt["words"])
    assert attempt["prosody"] is None, "a transcript cannot evidence prosody"

    quota = (await client.get("/v1/drills", headers=account)).json()["quota"]
    assert quota["authoritative_scoring_available"] is False
    assert "Azure" in quota["note"] or "ffmpeg" in quota["note"]


async def test_the_best_attempt_is_kept_not_the_latest(
    client: httpx.AsyncClient, account: dict
) -> None:
    sid = await _session_with_voice(client, account)
    drill = (await client.post("/v1/drills", headers=account, json={"session_id": sid})).json()[
        "drills"
    ][0]
    scores = []
    for seconds in (2.0, 0.8):
        response = await client.post(
            f"/v1/drills/{drill['id']}/attempts",
            headers=account,
            files={"audio": ("a.wav", wav_bytes(seconds), "audio/wav")},
        )
        scores.append(response.json()["accuracy"])

    detail = (await client.get(f"/v1/drills/{drill['id']}", headers=account)).json()
    assert len(detail["attempts"]) == 2
    assert detail["best_accuracy"] == max(scores)


async def test_reference_audio_is_served_for_a_drill(
    client: httpx.AsyncClient, account: dict
) -> None:
    sid = await _session_with_voice(client, account)
    drill = (await client.post("/v1/drills", headers=account, json={"session_id": sid})).json()[
        "drills"
    ][0]
    response = await client.get(f"/v1/drills/{drill['id']}/reference-audio", headers=account)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/")


async def test_hand_written_drill_sentences_are_accepted(
    client: httpx.AsyncClient, account: dict
) -> None:
    response = await client.post(
        "/v1/drills",
        headers=account,
        json={"language": "de", "sentences": ["Ich hätte gern ein großes Bier."]},
    )
    assert response.status_code == 201
    assert response.json()["drills"][0]["ref_text"] == "Ich hätte gern ein großes Bier."


async def test_drills_need_a_session_or_sentences(client: httpx.AsyncClient, account: dict) -> None:
    assert (await client.post("/v1/drills", headers=account, json={})).status_code == 422


# ── progress and usage ──────────────────────────────────────────────────────
async def test_progress_aggregates_sessions_words_and_the_skill_radar(
    client: httpx.AsyncClient, account: dict
) -> None:
    session = await start_session(client, account, "de-bakery-a1", target_turns=6)
    for _ in range(6):
        body = await run_turn(client, account, session["session_id"], "Zwei Brötchen, bitte.")
        if events_named(body, "turn_state")[0]["ended"]:
            break
    await client.get(
        f"/v1/sessions/{session['session_id']}/report", headers=account, params={"wait": "true"}
    )
    await client.post(
        "/v1/vocab", headers=account, json={"language": "de", "term": "Brötchen", "meaning": "roll"}
    )

    response = await client.get("/v1/progress", headers=account)
    assert response.status_code == 200
    progress = response.json()
    assert progress["sessions_total"] == 1
    assert progress["streak_days"] >= 1
    assert progress["words_learned"] == 1
    assert progress["score_trend"]
    assert progress["skill_radar"]["grammar"] > 0
    german = next(row for row in progress["by_language"] if row["language"] == "de")
    assert german["sessions"] == 1
    assert german["latest_cefr"]


async def test_usage_meters_describe_the_free_tier(
    client: httpx.AsyncClient, account: dict
) -> None:
    response = await client.get("/v1/usage", headers=account)
    assert response.status_code == 200
    meters = {meter["key"]: meter for meter in response.json()["meters"]}
    assert set(meters) == {"sessions", "premium_tts", "pronunciation"}
    assert meters["premium_tts"]["unit"] == "characters"
    assert meters["pronunciation"]["resets"] == "monthly"
    assert response.json()["byok_active"] is False

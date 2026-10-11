from __future__ import annotations

import httpx
from conftest import events_named, run_turn, start_session, wav_bytes


async def _finish(
    client: httpx.AsyncClient, headers: dict, scenario_id: str, turns: int = 6
) -> str:
    """Run a scenario to its end, respecting that scenario's own turn minimum."""
    brief = (await client.get(f"/v1/scenarios/{scenario_id}")).json()
    turns = max(turns, brief["turn_limits"]["min"])
    session = await start_session(client, headers, scenario_id, target_turns=turns)
    sid = session["session_id"]
    for _ in range(turns):
        body = await run_turn(client, headers, sid, "네, 김민수로 예약했어요. 조식은 몇 시예요?")
        if events_named(body, "turn_state")[0]["ended"]:
            break
    return sid


async def test_report_is_scored_from_its_documented_rubric(
    client: httpx.AsyncClient, account: dict
) -> None:
    sid = await _finish(client, account, "ko-hotel-checkin-a2")
    response = await client.get(
        f"/v1/sessions/{sid}/report", headers=account, params={"wait": "true"}
    )
    assert response.status_code == 200
    report = response.json()

    assert 0 <= report["overall"] <= 100
    weights = report["scores"]["weights"]
    assert weights == {
        "task_completion": 0.30,
        "grammar": 0.25,
        "fluency": 0.20,
        "pronunciation": 0.15,
        "vocabulary": 0.10,
    }
    assert abs(sum(weights.values()) - 1.0) < 1e-9

    # Goal state comes from the orchestrator, not the model's opinion of it.
    assert report["goals"]["total"] == 4
    assert report["goals"]["done"] == sum(1 for g in report["goals"]["items"] if g["done"])


async def test_a_text_only_session_reports_no_pronunciation_score(
    client: httpx.AsyncClient, account: dict
) -> None:
    """Nothing to hear means no estimate — and a null, not a zero (ADR 0003)."""
    sid = await _finish(client, account, "ko-restaurant-order-a2")
    report = (
        await client.get(f"/v1/sessions/{sid}/report", headers=account, params={"wait": "true"})
    ).json()

    assert report["scores"]["pronunciation"] is None
    assert report["scores"]["pronunciation_basis"] == "unavailable"
    assert report["scores"]["excluded_from_overall"] == ["pronunciation"]
    assert report["speaking"]["estimated_from_text"] is True


async def test_pronunciation_is_labelled_as_an_estimate(
    client: httpx.AsyncClient, account: dict
) -> None:
    session = await start_session(client, account, "ja-konbini-a1", target_turns=6, input="voice")
    sid = session["session_id"]
    for _ in range(6):
        response = await client.post(
            f"/v1/sessions/{sid}/turns",
            headers=account,
            files={"audio": ("t.wav", wav_bytes(2.5), "audio/wav")},
            data={"client_transcript": "おにぎりはどこですか", "response_delay_ms": "2000"},
        )
        if events_named(response.text, "turn_state")[0]["ended"]:
            break

    report = (
        await client.get(f"/v1/sessions/{sid}/report", headers=account, params={"wait": "true"})
    ).json()
    pron = report["pronunciation"]
    assert pron["confidence"] == "estimated"
    assert pron["basis"] == "stt_confidence"
    assert "drills" in pron["disclaimer"]
    assert pron["focus_areas"], "per-language focus notes come from the plan's checklist"
    # Fluency is measured from the word timings, not guessed by a model.
    assert report["speaking"]["estimated_from_text"] is False
    assert report["speaking"]["chars_per_minute"] > 0
    assert report["speaking"]["avg_response_delay_ms"] == 2000


async def test_report_creates_drills_and_recommends_a_next_scenario(
    client: httpx.AsyncClient, account: dict
) -> None:
    sid = await _finish(client, account, "ko-hotel-checkin-a2")
    report = (
        await client.get(f"/v1/sessions/{sid}/report", headers=account, params={"wait": "true"})
    ).json()

    drills = report["pronunciation"]["drills"]
    assert 1 <= len(drills) <= 4
    assert all(drill["ref_text"] for drill in drills)

    next_id = report["next_steps"]["next_scenario_id"]
    assert next_id and next_id != "ko-hotel-checkin-a2"
    assert next_id.startswith("ko-")


async def test_report_is_generated_once_and_then_cached(
    client: httpx.AsyncClient, account: dict
) -> None:
    sid = await _finish(client, account, "de-bakery-a1", turns=6)
    first = await client.get(f"/v1/sessions/{sid}/report", headers=account, params={"wait": "true"})
    second = await client.get(f"/v1/sessions/{sid}/report", headers=account)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()

    state = await client.get(f"/v1/sessions/{sid}", headers=account)
    assert state.json()["status"] == "completed"
    assert state.json()["report_ready"] is True


async def test_polling_answers_202_until_it_is_ready(
    client: httpx.AsyncClient, account: dict
) -> None:
    sid = await _finish(client, account, "en-coffee-shop-a1", turns=6)
    response = await client.get(f"/v1/sessions/{sid}/report", headers=account)
    assert response.status_code in (200, 202)
    if response.status_code == 202:
        assert response.json()["status"] == "analyzing"
        assert response.json()["eta_s"] > 0


async def test_report_on_a_live_session_is_refused(
    client: httpx.AsyncClient, account: dict
) -> None:
    session = await start_session(client, account, "ko-cafe-order-a1", target_turns=6)
    await run_turn(client, account, session["session_id"], "아이스 아메리카노 주세요.")
    response = await client.get(f"/v1/sessions/{session['session_id']}/report", headers=account)
    assert response.status_code == 409
    assert "still going" in response.json()["detail"]


async def test_register_check_runs_for_korean(client: httpx.AsyncClient, account: dict) -> None:
    sid = await _finish(client, account, "ko-job-interview-b1", turns=10)
    report = (
        await client.get(f"/v1/sessions/{sid}/report", headers=account, params={"wait": "true"})
    ).json()
    register = report["register"]
    # The persona speaks 합쇼체, so the expected register is formal.
    assert register["expected"] == "formal"
    assert register["language"] == "ko"
    # The learner's lines were 해요체 throughout, which is the wrong level here.
    assert register["consistent"] is False
    assert register["offending_turns"]


async def test_guest_report_does_not_silently_create_flashcards(
    client: httpx.AsyncClient, guest: dict
) -> None:
    sid = await _finish(client, guest, "ko-cafe-order-a1", turns=6)
    report = (
        await client.get(f"/v1/sessions/{sid}/report", headers=guest, params={"wait": "true"})
    ).json()
    assert report["vocabulary"]["requires_account"] is True
    assert report["vocabulary"]["flashcards_created"] == []


async def test_transcript_is_in_the_report(client: httpx.AsyncClient, account: dict) -> None:
    sid = await _finish(client, account, "ko-hotel-checkin-a2")
    report = (
        await client.get(f"/v1/sessions/{sid}/report", headers=account, params={"wait": "true"})
    ).json()
    lines = report["transcript"]
    assert lines[0]["role"] == "ai", "the authored opening line is turn 0"
    assert any(line["role"] == "user" for line in lines)
    assert [line["idx"] for line in lines] == sorted(line["idx"] for line in lines)

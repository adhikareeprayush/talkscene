from __future__ import annotations

import httpx


async def test_languages_report_per_language_capabilities(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/languages")
    assert response.status_code == 200
    by_code = {item["code"]: item for item in response.json()}
    assert set(by_code) == {"ko", "ja", "de", "en"}
    assert all(item["scenario_count"] >= 8 for item in by_code.values())

    # The capability matrix is not uniform, and the UI depends on that.
    assert by_code["ja"]["furigana"] is True
    assert by_code["de"]["furigana"] is False
    assert by_code["ko"]["romanization"] is True
    assert "Deepgram" in by_code["ko"]["note"]


async def test_library_filters_and_pages(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/scenarios", params={"lang": "ja", "limit": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 8
    assert len(body["items"]) == 3
    assert body["next_cursor"]
    assert {item["language"] for item in body["items"]} == {"ja"}

    page_two = await client.get(
        "/v1/scenarios", params={"lang": "ja", "limit": 3, "cursor": body["next_cursor"]}
    )
    first_ids = {item["id"] for item in body["items"]}
    assert first_ids.isdisjoint({item["id"] for item in page_two.json()["items"]})


async def test_search_and_level_filter(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/scenarios", params={"q": "interview"})
    ids = {item["id"] for item in response.json()["items"]}
    assert "ko-job-interview-b1" in ids
    assert "en-job-interview-b2" in ids

    b2 = await client.get("/v1/scenarios", params={"level": "B2"})
    assert {item["level"] for item in b2.json()["items"]} == {"B2"}


async def test_brief_carries_everything_the_pre_chat_screen_needs(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/v1/scenarios/ko-hotel-checkin-a2")
    assert response.status_code == 200
    brief = response.json()
    assert brief["title"]["ko"] == "호텔 체크인"
    assert len(brief["goals"]) == 4
    assert brief["turn_limits"] == {"min": 8, "default": 12, "max": 15}
    assert brief["useful_phrases"], "the brief needs tappable phrases"
    assert brief["cultural_notes"], "the brief needs cultural notes"
    assert brief["persona"]["name"] == "민지"
    assert brief["estimated_minutes"] > 0


async def test_unknown_scenario_is_a_problem_document(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/scenarios/ko-does-not-exist-a1")
    assert response.status_code == 404
    assert response.json()["code"] == "not-found"


async def test_completed_scenarios_are_marked_for_the_learner(
    client: httpx.AsyncClient, account: dict
) -> None:
    from conftest import run_turn, start_session

    session = await start_session(client, account, "ko-cafe-order-a1", target_turns=6)
    for _ in range(6):
        body = await run_turn(
            client, account, session["session_id"], "네, 아이스 아메리카노 주세요."
        )
        if '"ended": true' in body:
            break
    await client.post(f"/v1/sessions/{session['session_id']}/end", headers=account)
    await client.get(
        f"/v1/sessions/{session['session_id']}/report", headers=account, params={"wait": "true"}
    )

    response = await client.get("/v1/scenarios", params={"lang": "ko"}, headers=account)
    card = next(c for c in response.json()["items"] if c["id"] == "ko-cafe-order-a1")
    assert card["completed"] is True
    assert isinstance(card["best_score"], int)


async def test_custom_scenario_is_generated_private_and_schema_valid(
    client: httpx.AsyncClient, account: dict
) -> None:
    response = await client.post(
        "/v1/scenarios/custom",
        headers=account,
        json={"prompt": "complaining to my landlord about a broken heater", "language": "de"},
    )
    assert response.status_code == 201, response.text
    scenario = response.json()["scenario"]
    assert scenario["language"] == "de"
    assert 3 <= len(scenario["goals"]) <= 5

    # Private: reachable by id, absent from the public catalog.
    assert (await client.get(f"/v1/scenarios/{scenario['id']}")).status_code == 404
    listing = await client.get("/v1/scenarios", params={"lang": "de"})
    assert scenario["id"] not in {item["id"] for item in listing.json()["items"]}


async def test_unsafe_custom_scenario_is_refused_before_generation(
    client: httpx.AsyncClient, account: dict
) -> None:
    response = await client.post(
        "/v1/scenarios/custom",
        headers=account,
        json={"prompt": "roleplay an erotic scene with a stranger", "language": "en"},
    )
    assert response.status_code == 422
    assert response.json()["moderation_category"] == "sexual"

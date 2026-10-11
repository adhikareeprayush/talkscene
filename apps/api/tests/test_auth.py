from __future__ import annotations

import httpx


async def test_guest_gets_a_usable_token(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/auth/guest", json={"native_lang": "en"})
    assert response.status_code == 201
    body = response.json()
    assert body["is_guest"] is True
    assert body["token_type"] == "Bearer"

    me = await client.get("/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["is_guest"] is True


async def test_missing_token_is_a_problem_document(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/me")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "unauthorized"


async def test_signup_links_an_existing_guest_so_history_survives(
    client: httpx.AsyncClient,
) -> None:
    guest = (await client.post("/v1/auth/guest", json={})).json()
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": "Sam@Example.com",
            "password": "a-long-enough-password",
            "link_guest_token": guest["access_token"],
        },
    )
    assert response.status_code == 201
    # Same row upgraded in place, so sessions recorded as a guest are kept.
    assert response.json()["user_id"] == guest["user_id"]
    assert response.json()["is_guest"] is False


async def test_duplicate_email_conflicts(client: httpx.AsyncClient, account: dict) -> None:
    response = await client.post(
        "/v1/auth/signup",
        json={"email": "learner@example.com", "password": "another-long-password"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_login_does_not_reveal_whether_the_email_exists(
    client: httpx.AsyncClient, account: dict
) -> None:
    wrong_password = await client.post(
        "/v1/auth/login", json={"email": "learner@example.com", "password": "nope"}
    )
    unknown_email = await client.post(
        "/v1/auth/login", json={"email": "nobody@example.com", "password": "nope"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


async def test_login_then_refresh(client: httpx.AsyncClient, account: dict) -> None:
    login = await client.post(
        "/v1/auth/login",
        json={"email": "learner@example.com", "password": "a-long-enough-password"},
    )
    assert login.status_code == 200
    refreshed = await client.post(
        "/v1/auth/refresh", json={"refresh_token": login.json()["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["user_id"] == login.json()["user_id"]


async def test_access_token_is_rejected_where_a_refresh_token_is_expected(
    client: httpx.AsyncClient, account: dict
) -> None:
    token = account["Authorization"].split(" ", 1)[1]
    response = await client.post("/v1/auth/refresh", json={"refresh_token": token})
    assert response.status_code == 401


async def test_byok_keys_are_never_returned(client: httpx.AsyncClient, account: dict) -> None:
    response = await client.patch(
        "/v1/me", headers=account, json={"byok": {"groq": "gsk_secret_value"}}
    )
    assert response.status_code == 200
    assert response.json()["byok_configured"] == ["groq"]
    assert "gsk_secret_value" not in response.text
    # A BYOK learner spends their own quota, so the service limit lifts.
    usage = await client.get("/v1/usage", headers=account)
    assert usage.json()["byok_active"] is True
    assert usage.json()["meters"][0]["limit"] is None

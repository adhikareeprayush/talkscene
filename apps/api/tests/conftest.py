"""Test fixtures.

Everything runs on mock providers against an in-memory SQLite database, so the
suite needs no network, no keys and no services — which is the point of the
last-resort adapters in ADR 0002.
"""

from __future__ import annotations

import io
import os
import struct
import wave
from collections.abc import AsyncIterator

# Must be set before `talkscene.core.config` is imported: Settings is cached.
os.environ.update(
    TS_ENV="test",
    TS_PROVIDER_MODE="mock",
    TS_SECRET_KEY="test-secret-key-not-for-production",
    TS_LOG_LEVEL="WARNING",
    DATABASE_URL="sqlite+aiosqlite:///:memory:",
    REDIS_URL="",
    QUOTA_SESSIONS_PER_DAY="0",
    AUDIO_RETENTION_DAYS="30",
)

import httpx
import pytest

from talkscene.core import cache as cache_mod
from talkscene.core import storage as storage_mod
from talkscene.main import create_app


class _MemoryStorage:
    """Audio in a dict: no temp directories left behind between tests."""

    name = "memory"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        self.objects[key] = data
        return key

    async def get(self, key: str) -> bytes | None:
        return self.objects.get(key)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def purge_older_than(self, days: int) -> int:
        return 0


@pytest.fixture
async def app() -> AsyncIterator[object]:
    cache_mod.set_cache(cache_mod.MemoryCache())
    storage_mod.set_storage(_MemoryStorage())
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application
    await cache_mod.close_cache()
    cache_mod.set_cache(cache_mod.MemoryCache())


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
async def guest(client: httpx.AsyncClient) -> dict[str, str]:
    """Headers for a fresh anonymous learner."""
    response = await client.post("/v1/auth/guest", json={"native_lang": "en"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def account(client: httpx.AsyncClient) -> dict[str, str]:
    """Headers for a registered learner (vocabulary needs an account)."""
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": "learner@example.com",
            "password": "a-long-enough-password",
            "display_name": "Learner",
            "native_lang": "en",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def wav_bytes(seconds: float = 2.0, amplitude: int = 2500) -> bytes:
    """A real 16 kHz mono WAV, so duration and RMS checks see valid input."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(struct.pack("<h", amplitude) * int(16000 * seconds))
    return buf.getvalue()


def sse_events(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE response body into `[(event, data), ...]`."""
    import json

    out: list[tuple[str, dict]] = []
    name = ""
    for line in body.splitlines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            out.append((name, json.loads(line[6:])))
    return out


def events_named(body: str, name: str) -> list[dict]:
    return [data for event, data in sse_events(body) if event == name]


async def run_turn(
    client: httpx.AsyncClient, headers: dict[str, str], session_id: str, text: str
) -> str:
    response = await client.post(
        f"/v1/sessions/{session_id}/turns", headers=headers, json={"text": text}
    )
    assert response.status_code == 200, response.text
    return response.text


async def start_session(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    scenario_id: str = "ko-hotel-checkin-a2",
    *,
    target_turns: int = 8,
    **options,
) -> dict:
    response = await client.post(
        "/v1/sessions",
        headers=headers,
        json={
            "scenario_id": scenario_id,
            "target_turns": target_turns,
            "options": {"input": "text", **options},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()

"""One shared httpx client for every adapter.

Centralising it means connection reuse (which matters for first-token latency),
one timeout policy, and one place that translates transport failures into the
`ProviderError` family the router switches on.
"""

from __future__ import annotations

import httpx

from .base import ProviderRateLimited, ProviderUnavailable

_client: httpx.AsyncClient | None = None

# Generous read timeout: LLM streams hold the connection open between tokens.
TIMEOUT = httpx.Timeout(connect=5.0, read=90.0, write=30.0, pool=5.0)


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=TIMEOUT,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def retry_after(response: httpx.Response, default: float = 30.0) -> float:
    raw = response.headers.get("retry-after")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def raise_for_provider(provider: str, response: httpx.Response) -> None:
    """Map an HTTP status onto the exception the router expects."""
    if response.status_code == 429:
        raise ProviderRateLimited(provider, retry_after(response))
    if response.status_code >= 500:
        raise ProviderUnavailable(provider, f"HTTP {response.status_code}")
    if response.status_code >= 400:
        body = response.text[:300]
        # 401/403 are configuration faults, not transient - still fail over,
        # but the message has to say which it was.
        raise ProviderUnavailable(provider, f"HTTP {response.status_code}: {body}")


def transport_error(provider: str, exc: Exception) -> ProviderUnavailable:
    return ProviderUnavailable(provider, f"{type(exc).__name__}: {exc}")

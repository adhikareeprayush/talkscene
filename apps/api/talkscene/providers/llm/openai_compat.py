"""One adapter for every OpenAI-compatible chat endpoint.

Groq, xAI Grok, Gemini (its `/v1beta/openai` surface) and a local Ollama all
speak the same protocol, so they differ only in `base_url`, key and model —
which is exactly the swap-by-config property ADR 0002 is after.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from ..base import Msg, ProviderNotConfigured, ProviderUnavailable
from ..http import client, raise_for_provider, transport_error


class OpenAICompatLLM:
    def __init__(self, name: str, base_url: str, api_key: str, model: str) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat_stream(
        self,
        messages: list[Msg],
        *,
        temperature: float = 0.7,
        max_tokens: int = 320,
        json_mode: bool = False,
        stop: list[str] | None = None,
    ) -> AsyncIterator[str]:
        if not self.configured:
            raise ProviderNotConfigured(self.name)

        payload: dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if stop:
            payload["stop"] = stop

        url = f"{self.base_url}/chat/completions"
        try:
            async with client().stream("POST", url, headers=self._headers(), json=payload) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise_for_provider(self.name, resp)
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data in ("", "[DONE]"):
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield piece
        except httpx.HTTPError as exc:
            raise transport_error(self.name, exc) from exc

    async def complete(
        self,
        messages: list[Msg],
        *,
        temperature: float = 0.3,
        max_tokens: int = 900,
        json_mode: bool = False,
    ) -> str:
        """Non-streamed convenience path, used for feedback and hint calls."""
        if not self.configured:
            raise ProviderNotConfigured(self.name)
        payload: dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            resp = await client().post(
                f"{self.base_url}/chat/completions", headers=self._headers(), json=payload
            )
        except httpx.HTTPError as exc:
            raise transport_error(self.name, exc) from exc
        raise_for_provider(self.name, resp)
        body = resp.json()
        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailable(self.name, f"malformed response: {body}") from exc

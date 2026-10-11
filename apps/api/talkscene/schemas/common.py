from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Lang = Literal["ko", "ja", "de", "en"]
Level = Literal["A1", "A2", "B1", "B2"]
Category = Literal[
    "travel", "food", "shopping", "health", "services", "social", "work", "culture", "emergencies"
]


class Schema(BaseModel):
    # In responses a field with a default is always present, so the exported
    # contract must say so - otherwise every generated client type marks it
    # optional and the UI fills with `?? []`. Request bodies are unaffected:
    # FastAPI emits separate -Input/-Output schemas where the two differ.
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_serialization_defaults_required=True,
    )


class Problem(Schema):
    """RFC 9457 problem document. Every non-2xx response uses this shape."""

    model_config = ConfigDict(extra="allow", json_schema_serialization_defaults_required=True)

    type: str = Field(examples=["https://talkscene.app/problems/quota-exceeded"])
    title: str
    status: int
    detail: str
    code: str
    instance: str | None = None


class Page[T](Schema):
    items: list[T]
    next_cursor: str | None = Field(
        None, description="Opaque cursor; pass as `cursor` to fetch the next page."
    )
    total: int | None = None


class Ok(Schema):
    ok: bool = True
    detail: str | None = None


class AudioRef(Schema):
    url: str
    provider: str | None = None
    content_type: str = "audio/mpeg"
    cached: bool = False


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Attach the problem+json schema to a route's error responses."""
    titles = {
        400: "Bad request",
        401: "Not authenticated",
        403: "Forbidden",
        404: "Not found",
        409: "Conflict",
        413: "Payload too large",
        422: "Validation failed",
        429: "Rate limited or quota exceeded",
        503: "No provider available",
    }
    return {
        status: {
            "description": titles.get(status, "Error"),
            "model": Problem,
            "content": {"application/problem+json": {}},
        }
        for status in statuses
    }

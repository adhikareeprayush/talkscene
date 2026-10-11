"""RFC 9457 problem+json error handling (plan §10 conventions)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

CONTENT_TYPE = "application/problem+json"
BASE_URI = "https://talkscene.app/problems"


class ProblemError(Exception):
    """An error that renders itself as an RFC 9457 problem document."""

    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        *,
        title: str | None = None,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        self.status = status
        self.code = code
        self.detail = detail
        self.title = title or code.replace("-", " ").replace("_", " ").title()
        self.headers = headers or {}
        self.extra = extra
        super().__init__(detail)

    def to_dict(self, instance: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": f"{BASE_URI}/{self.code}",
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "code": self.code,
        }
        if instance:
            body["instance"] = instance
        body.update(self.extra)
        return body


# ── the specific failures the product actually has ──────────────────────────
def unauthorized(detail: str = "Missing or invalid credentials.") -> ProblemError:
    return ProblemError(401, "unauthorized", detail, headers={"WWW-Authenticate": "Bearer"})


def forbidden(detail: str = "You do not have access to this resource.") -> ProblemError:
    return ProblemError(403, "forbidden", detail)


def not_found(what: str = "Resource") -> ProblemError:
    return ProblemError(404, "not-found", f"{what} not found.")


def conflict(detail: str) -> ProblemError:
    return ProblemError(409, "conflict", detail)


def unprocessable(detail: str, **extra: Any) -> ProblemError:
    return ProblemError(422, "unprocessable", detail, **extra)


def quota_exceeded(resource: str, *, limit: int, resets_at: str | None = None) -> ProblemError:
    return ProblemError(
        429,
        "quota-exceeded",
        f"Daily limit for {resource} reached ({limit}). "
        f"It resets at {resets_at or 'midnight UTC'}.",
        title="Quota Exceeded",
        resource=resource,
        limit=limit,
        resets_at=resets_at,
    )


def rate_limited(retry_after: int) -> ProblemError:
    return ProblemError(
        429,
        "rate-limited",
        f"Too many requests. Retry in {retry_after}s.",
        headers={"Retry-After": str(retry_after)},
        retry_after=retry_after,
    )


def provider_unavailable(capability: str, tried: list[str]) -> ProblemError:
    return ProblemError(
        503,
        "provider-unavailable",
        f"No {capability} provider is currently available.",
        title="Provider Unavailable",
        capability=capability,
        tried=tried,
    )


def audio_too_large(limit_bytes: int) -> ProblemError:
    return ProblemError(
        413,
        "audio-too-large",
        f"Audio must be at most {limit_bytes // 1024}KB.",
        limit_bytes=limit_bytes,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return JSONResponse(
            exc.to_dict(str(request.url.path)),
            status_code=exc.status,
            media_type=CONTENT_TYPE,
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        problem = ProblemError(exc.status_code, "http-error", str(exc.detail))
        return JSONResponse(
            problem.to_dict(str(request.url.path)),
            status_code=exc.status_code,
            media_type=CONTENT_TYPE,
            headers=getattr(exc, "headers", None) or {},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        problem = ProblemError(
            422,
            "validation-failed",
            "The request body or parameters are invalid.",
            errors=[
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
            ],
        )
        return JSONResponse(
            problem.to_dict(str(request.url.path)), status_code=422, media_type=CONTENT_TYPE
        )

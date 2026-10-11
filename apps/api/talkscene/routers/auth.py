"""Authentication: guest tokens, email accounts, refresh (plan §10.1, §15)."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from ..core.config import settings
from ..core.errors import conflict, unauthorized, unprocessable
from ..core.ratelimit import Limit, enforce
from ..core.security import create_token, decode_token, hash_password, token_pair, verify_password
from ..deps import Db
from ..models.session import PracticeSession
from ..models.user import User, UserPref
from ..schemas.auth import GuestRequest, LoginRequest, RefreshRequest, SignupRequest, TokenPair
from ..schemas.common import problem_responses

router = APIRouter(prefix="/v1/auth", tags=["auth"])

GUEST_LIMIT = Limit(count=5, per_s=3600)
LOGIN_LIMIT = Limit(count=10, per_s=900)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post(
    "/guest",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    summary="Create an anonymous guest identity",
    description=(
        "Guests can run conversations immediately. The token is short-lived and guest accounts "
        "cannot own vocabulary or drills — signing up links the sessions they already recorded."
    ),
    responses=problem_responses(422, 429),
)
async def create_guest(body: GuestRequest, request: Request, db: Db) -> TokenPair:
    await enforce(_client_key(request), GUEST_LIMIT, scope="auth:guest")
    if settings.is_prod and not body.turnstile_token:
        # Guest creation is the cheapest thing to abuse, so production demands
        # a CAPTCHA token (plan §15).
        raise unprocessable("A Turnstile token is required to create a guest session.")

    user = User(is_guest=True, native_lang=body.native_lang, ui_lang=body.native_lang, plan="free")
    db.add(user)
    await db.flush()
    db.add(UserPref.defaults(user.id))
    await db.flush()
    return TokenPair(**token_pair(user.id, is_guest=True), user_id=user.id, is_guest=True)


@router.post(
    "/signup",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    responses=problem_responses(409, 422, 429),
)
async def signup(body: SignupRequest, request: Request, db: Db) -> TokenPair:
    await enforce(_client_key(request), LOGIN_LIMIT, scope="auth:signup")
    email = body.email.lower()
    if await db.scalar(select(User.id).where(User.email == email)):
        raise conflict("An account with that email already exists.")

    user: User | None = None
    if body.link_guest_token:
        # Upgrade the guest row in place so their history survives the signup.
        try:
            payload = decode_token(body.link_guest_token)
        except Exception:
            payload = {}
        candidate = await db.get(User, payload.get("sub", "")) if payload else None
        if candidate is not None and candidate.is_guest:
            user = candidate

    if user is None:
        user = User()
        db.add(user)
        await db.flush()
        db.add(UserPref.defaults(user.id))

    user.email = email
    user.password_hash = hash_password(body.password)
    user.display_name = body.display_name
    user.native_lang = body.native_lang
    user.is_guest = False
    await db.flush()
    return TokenPair(**token_pair(user.id), user_id=user.id, is_guest=False)


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Sign in with email and password",
    responses=problem_responses(401, 429),
)
async def login(body: LoginRequest, request: Request, db: Db) -> TokenPair:
    await enforce(_client_key(request), LOGIN_LIMIT, scope="auth:login")
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    # Same message either way: do not reveal whether the address exists.
    if (
        user is None
        or not user.password_hash
        or not verify_password(body.password, user.password_hash)
    ):
        raise unauthorized("Email or password is incorrect.")
    if user.deleted_at is not None:
        raise unauthorized("This account has been deleted.")
    return TokenPair(**token_pair(user.id), user_id=user.id, is_guest=False)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Exchange a refresh token",
    responses=problem_responses(401),
)
async def refresh(body: RefreshRequest, db: Db) -> TokenPair:
    payload = decode_token(body.refresh_token, expect="refresh")
    user = await db.get(User, payload["sub"])
    if user is None or user.deleted_at is not None:
        raise unauthorized("Account no longer exists.")
    return TokenPair(
        access_token=create_token(user.id, is_guest=user.is_guest),
        refresh_token=body.refresh_token,
        expires_in=settings.guest_token_ttl_s if user.is_guest else settings.access_token_ttl_s,
        user_id=user.id,
        is_guest=user.is_guest,
    )


@router.get(
    "/guest/sessions",
    summary="How many sessions a guest has recorded",
    include_in_schema=False,
)
async def guest_session_count(db: Db, request: Request) -> dict[str, int]:
    """Used by the UI to decide when to prompt a guest to sign up."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return {"sessions": 0}
    try:
        payload = decode_token(auth.split(" ", 1)[1])
    except Exception:
        return {"sessions": 0}
    rows = await db.scalars(
        select(PracticeSession.id).where(PracticeSession.user_id == payload["sub"])
    )
    return {"sessions": len(list(rows))}

"""JWT issue/verify and password hashing.

Hashing uses PBKDF2-HMAC-SHA256 from the standard library: no native wheels in
the API image.  Swap to Argon2id behind this interface if a GPU-attacker threat
model ever applies.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any, Literal

import jwt

from .config import settings
from .errors import unauthorized

ALGO = "HS256"
TokenKind = Literal["access", "refresh"]
_PBKDF2_ROUNDS = 390_000


# ── passwords ────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected.hex(), digest_hex)


# ── tokens ───────────────────────────────────────────────────────────────────
def create_token(
    subject: str, *, kind: TokenKind = "access", is_guest: bool = False, ttl_s: int | None = None
) -> str:
    if ttl_s is None:
        if kind == "refresh":
            ttl_s = settings.refresh_token_ttl_s
        else:
            ttl_s = settings.guest_token_ttl_s if is_guest else settings.access_token_ttl_s
    now = int(time.time())
    payload = {
        "sub": subject,
        "kind": kind,
        "guest": is_guest,
        "iat": now,
        "exp": now + ttl_s,
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGO)


def decode_token(token: str, *, expect: TokenKind = "access") -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGO])
    except jwt.ExpiredSignatureError as exc:
        raise unauthorized("Token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise unauthorized("Token is not valid.") from exc
    if payload.get("kind") != expect:
        raise unauthorized(f"Expected a {expect} token.")
    return payload


def token_pair(subject: str, *, is_guest: bool = False) -> dict[str, Any]:
    return {
        "access_token": create_token(subject, kind="access", is_guest=is_guest),
        "refresh_token": create_token(subject, kind="refresh", is_guest=is_guest),
        "token_type": "Bearer",
        "expires_in": settings.guest_token_ttl_s if is_guest else settings.access_token_ttl_s,
    }

"""Sealed storage for learner-supplied provider keys (BYOK, plan §15).

AES-256-GCM with a key derived from `TS_SECRET_KEY` via HKDF-SHA256 and a
fixed info string, so the app secret is never used directly as an encryption
key.  Authenticated encryption matters here: a tampered ciphertext must fail
loudly rather than decrypt to garbage that then gets sent to a vendor as a
bearer token.

In production the derivation key belongs in a KMS, and `TS_SECRET_KEY` must not
be the development default — `readyz` reports that as degraded.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import settings

NONCE_BYTES = 12
_INFO = b"talkscene/byok/v1"


def _key() -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
        settings.secret_key.encode()
    )


def seal(plaintext: str) -> str:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(_key()).encrypt(nonce, plaintext.encode(), _INFO)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()


def unseal(token: str) -> str | None:
    """None on any failure — a wrong secret, a tampered value, or old garbage."""
    try:
        raw = base64.urlsafe_b64decode(token.encode())
        nonce, ciphertext = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
        return AESGCM(_key()).decrypt(nonce, ciphertext, _INFO).decode()
    except Exception:
        return None


def seal_map(values: Mapping[str, str | None]) -> dict[str, str]:
    return {k: seal(v) for k, v in values.items() if v}


def unseal_map(values: Mapping[str, str] | None) -> dict[str, str]:
    if not values:
        return {}
    out = {}
    for name, token in values.items():
        plain = unseal(token)
        if plain:
            out[name] = plain
    return out

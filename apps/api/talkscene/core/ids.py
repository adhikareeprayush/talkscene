"""Prefixed, time-sortable public identifiers (`ses_01J7Z...`).

ULID-style: 48-bit millisecond timestamp + 80 bits of randomness, Crockford
base32.  Sortable by creation time, URL-safe, and the prefix makes a stray id in
a log line self-describing.
"""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        out.append(_ALPHABET[rem])
    return "".join(reversed(out))


def ulid() -> str:
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    return _encode(ms, 10) + _encode(rand, 16)


def new_id(prefix: str) -> str:
    return f"{prefix}_{ulid()}"


# One helper per entity so the prefixes stay in one place.
def user_id() -> str:
    return new_id("usr")


def session_id() -> str:
    return new_id("ses")


def turn_id() -> str:
    return new_id("trn")


def report_id() -> str:
    return new_id("rep")


def drill_id() -> str:
    return new_id("drl")


def attempt_id() -> str:
    return new_id("att")


def vocab_id() -> str:
    return new_id("voc")


def card_id() -> str:
    return new_id("crd")


def ledger_id() -> str:
    return new_id("led")

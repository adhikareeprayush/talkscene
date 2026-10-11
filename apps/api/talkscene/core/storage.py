"""Audio storage.

Local filesystem by default (zero setup); S3/R2 when configured.  Callers deal
in opaque keys like `turns/ses_01J.../3.webm` and never in paths or URLs, so the
backend is swappable and retention can be enforced in one place.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Protocol

from .config import settings


class StorageBackend(Protocol):
    name: str

    async def put(self, key: str, data: bytes, content_type: str) -> str: ...
    async def get(self, key: str) -> bytes | None: ...
    async def delete(self, key: str) -> None: ...
    async def purge_older_than(self, days: int) -> int: ...


class LocalStorage:
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Keys are server-generated, but never trust one into a path join.
        safe = Path(key.replace("..", "_").lstrip("/"))
        target = (self.root / safe).resolve()
        if not str(target).startswith(str(self.root.resolve())):
            raise ValueError(f"unsafe storage key: {key!r}")
        return target

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    async def get(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    async def purge_older_than(self, days: int) -> int:
        cutoff = dt.datetime.now(dt.UTC).timestamp() - days * 86400
        removed = 0
        for path in self.root.rglob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        return removed


class S3Storage:
    name = "s3"

    def __init__(self) -> None:
        import boto3  # optional dependency

        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )
        self._bucket = settings.s3_bucket

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        import asyncio

        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    async def get(self, key: str) -> bytes | None:
        import asyncio

        def _fetch() -> bytes | None:
            try:
                return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
            except Exception:
                return None

        return await asyncio.to_thread(_fetch)

    async def delete(self, key: str) -> None:
        import asyncio

        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def purge_older_than(self, days: int) -> int:
        # R2/S3 lifecycle rules do this server-side; nothing to do here.
        return 0


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _backend
    if _backend is None:
        if settings.audio_storage == "s3" and settings.s3_bucket:
            try:
                _backend = S3Storage()
            except Exception:
                _backend = LocalStorage(settings.audio_path)
        else:
            _backend = LocalStorage(settings.audio_path)
    return _backend


def set_storage(backend: StorageBackend) -> None:
    global _backend
    _backend = backend


# ── key builders ────────────────────────────────────────────────────────────
def turn_audio_key(session_id: str, idx: int, role: str, ext: str = "webm") -> str:
    return f"turns/{session_id}/{idx}-{role}.{ext}"


def tts_cache_key(provider: str, voice: str, rate: float, text: str) -> str:
    digest = hashlib.sha256(f"{provider}|{voice}|{rate:.2f}|{text}".encode()).hexdigest()
    return f"tts/{digest[:2]}/{digest}.mp3"


def drill_audio_key(drill_id: str, attempt: int, ext: str = "webm") -> str:
    return f"drills/{drill_id}/{attempt}.{ext}"

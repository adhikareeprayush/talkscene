"""Audio inspection and transcoding.

Azure's pronunciation-assessment endpoint only accepts 16 kHz mono 16-bit PCM
WAV, but the browser records WebM/Opus.  ffmpeg is an *optional* dependency:
when it is missing, `to_wav16k` returns None and the pronunciation router
degrades to the heuristic provider, which labels itself non-authoritative
(ADR 0003) instead of pretending.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import io
import shutil
import struct
import wave


@functools.lru_cache(maxsize=1)
def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def is_wav_16k_mono(data: bytes) -> bool:
    if not data.startswith(b"RIFF"):
        return False
    with contextlib.suppress(Exception), wave.open(io.BytesIO(data), "rb") as w:
        return w.getnchannels() == 1 and w.getframerate() == 16000 and w.getsampwidth() == 2
    return False


async def to_wav16k(data: bytes, content_type: str = "audio/webm") -> bytes | None:
    """Transcode to the format Azure PA requires. None when ffmpeg is absent."""
    if is_wav_16k_mono(data):
        return data
    exe = ffmpeg_path()
    if not exe:
        return None
    proc = await asyncio.create_subprocess_exec(
        exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-sample_fmt",
        "s16",
        "-f",
        "wav",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, _err = await asyncio.wait_for(proc.communicate(data), timeout=30)
    except TimeoutError:
        proc.kill()
        return None
    return out if proc.returncode == 0 and out else None


def wav_duration_s(data: bytes) -> float:
    with contextlib.suppress(Exception), wave.open(io.BytesIO(data), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 1)
    return 0.0


def estimate_duration_s(data: bytes, content_type: str = "audio/webm") -> float:
    """Cheap duration estimate used for limit checks before any decoding."""
    if data.startswith(b"RIFF"):
        return wav_duration_s(data)
    # MediaRecorder webm/opus averages ~2.5 KB per second of speech.
    return len(data) / 2500.0


def peak_rms(data: bytes) -> float | None:
    """RMS level of a 16-bit PCM WAV, 0..1. Used for the noisy-audio warning."""
    if not data.startswith(b"RIFF"):
        return None
    with contextlib.suppress(Exception), wave.open(io.BytesIO(data), "rb") as w:
        if w.getsampwidth() != 2:
            return None
        frames = w.readframes(min(w.getnframes(), 16000 * 5))
        if not frames:
            return None
        samples = struct.unpack(f"<{len(frames) // 2}h", frames[: len(frames) // 2 * 2])
        if not samples:
            return None
        mean_square = sum(s * s for s in samples) / len(samples)
        return (mean_square**0.5) / 32768.0
    return None

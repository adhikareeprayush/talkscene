"""Runtime configuration.

Every setting has a default that works offline, so an empty environment still
boots a complete stack on mock providers (ADR 0002).  Model names are *never*
hard-coded in code — vendor rosters rotate, so they live here.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderMode = Literal["auto", "mock", "live"]
Lang = Literal["ko", "ja", "de", "en"]

REPO_ROOT = Path(__file__).resolve().parents[4]


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── app ──────────────────────────────────────────────────────────────────
    env: Literal["dev", "test", "prod"] = Field("dev", validation_alias="TS_ENV")
    log_level: str = Field("INFO", validation_alias="TS_LOG_LEVEL")
    secret_key: str = Field("dev-only-change-me-in-production", validation_alias="TS_SECRET_KEY")
    cors_origins: str = Field("http://localhost:3000", validation_alias="TS_CORS_ORIGINS")
    public_api_url: str = Field("http://localhost:8000", validation_alias="TS_PUBLIC_API_URL")
    provider_mode: ProviderMode = Field("auto", validation_alias="TS_PROVIDER_MODE")
    admin_token: str = Field("", validation_alias="TS_ADMIN_TOKEN")

    access_token_ttl_s: int = 3600
    refresh_token_ttl_s: int = 60 * 60 * 24 * 30
    guest_token_ttl_s: int = 60 * 60 * 24 * 7

    # ── storage ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        "sqlite+aiosqlite:///./var/talkscene.db", validation_alias="DATABASE_URL"
    )
    redis_url: str = Field("", validation_alias="REDIS_URL")
    audio_storage: Literal["local", "s3"] = Field("local", validation_alias="AUDIO_STORAGE")
    audio_dir: str = Field("./var/audio", validation_alias="AUDIO_DIR")
    audio_retention_days: int = Field(30, validation_alias="AUDIO_RETENTION_DAYS")
    s3_endpoint_url: str = Field("", validation_alias="S3_ENDPOINT_URL")
    s3_bucket: str = Field("", validation_alias="S3_BUCKET")
    s3_access_key_id: str = Field("", validation_alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field("", validation_alias="S3_SECRET_ACCESS_KEY")
    s3_public_base_url: str = Field("", validation_alias="S3_PUBLIC_BASE_URL")

    scenario_packs_dir: str = Field(
        str(REPO_ROOT / "packages" / "scenarios"), validation_alias="SCENARIO_PACKS_DIR"
    )

    # ── LLM ──────────────────────────────────────────────────────────────────
    # `ollama` is deliberately absent: it needs no key, so including it by
    # default would make every turn probe localhost on a fresh checkout.
    # Add it to LLM_PROVIDERS to use a local model.
    llm_providers: str = Field("groq,gemini,xai", validation_alias="LLM_PROVIDERS")
    llm_groq_base_url: str = Field(
        "https://api.groq.com/openai/v1", validation_alias="LLM_GROQ_BASE_URL"
    )
    llm_groq_model: str = Field("llama-3.3-70b-versatile", validation_alias="LLM_GROQ_MODEL")
    groq_api_key: str = Field("", validation_alias="GROQ_API_KEY")
    llm_gemini_base_url: str = Field(
        "https://generativelanguage.googleapis.com/v1beta/openai",
        validation_alias="LLM_GEMINI_BASE_URL",
    )
    llm_gemini_model: str = Field("gemini-2.0-flash", validation_alias="LLM_GEMINI_MODEL")
    gemini_api_key: str = Field("", validation_alias="GEMINI_API_KEY")
    llm_xai_base_url: str = Field("https://api.x.ai/v1", validation_alias="LLM_XAI_BASE_URL")
    llm_xai_model: str = Field("grok-3-mini", validation_alias="LLM_XAI_MODEL")
    xai_api_key: str = Field("", validation_alias="XAI_API_KEY")
    llm_ollama_base_url: str = Field(
        "http://localhost:11434/v1", validation_alias="LLM_OLLAMA_BASE_URL"
    )
    llm_ollama_model: str = Field("qwen2.5:7b-instruct", validation_alias="LLM_OLLAMA_MODEL")

    # ── STT ──────────────────────────────────────────────────────────────────
    stt_providers: str = Field("groq_whisper,deepgram,azure", validation_alias="STT_PROVIDERS")
    stt_groq_model: str = Field("whisper-large-v3-turbo", validation_alias="STT_GROQ_MODEL")
    deepgram_api_key: str = Field("", validation_alias="DEEPGRAM_API_KEY")
    stt_deepgram_model: str = Field("nova-3", validation_alias="STT_DEEPGRAM_MODEL")

    # ── TTS (per-language chains; `browser` is resolved client-side) ─────────
    tts_route_ko: str = Field("azure,browser", validation_alias="TTS_ROUTE_KO")
    tts_route_ja: str = Field("azure,deepgram,browser", validation_alias="TTS_ROUTE_JA")
    tts_route_de: str = Field("azure,deepgram,browser", validation_alias="TTS_ROUTE_DE")
    tts_route_en: str = Field("azure,deepgram,browser", validation_alias="TTS_ROUTE_EN")
    tts_deepgram_model: str = Field("aura-2-thalia-en", validation_alias="TTS_DEEPGRAM_MODEL")

    # ── Azure Speech (TTS + Pronunciation Assessment) ────────────────────────
    azure_speech_key: str = Field("", validation_alias="AZURE_SPEECH_KEY")
    azure_speech_region: str = Field("eastus", validation_alias="AZURE_SPEECH_REGION")
    pron_provider: Literal["azure", "heuristic"] = Field("azure", validation_alias="PRON_PROVIDER")

    # ── quotas ───────────────────────────────────────────────────────────────
    quota_sessions_per_day: int = Field(3, validation_alias="QUOTA_SESSIONS_PER_DAY")
    quota_plus_sessions_per_day: int = Field(0, validation_alias="QUOTA_PLUS_SESSIONS_PER_DAY")
    quota_hints_per_session: int = Field(20, validation_alias="QUOTA_HINTS_PER_SESSION")
    quota_premium_tts_chars_per_month: int = Field(
        40_000, validation_alias="QUOTA_PREMIUM_TTS_CHARS_PER_MONTH"
    )
    quota_drill_seconds_per_month: int = Field(
        600, validation_alias="QUOTA_DRILL_SECONDS_PER_MONTH"
    )
    max_audio_seconds: int = Field(30, validation_alias="MAX_AUDIO_SECONDS")
    max_audio_bytes: int = Field(5_242_880, validation_alias="MAX_AUDIO_BYTES")

    # ── derived helpers ──────────────────────────────────────────────────────
    @field_validator("cors_origins")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return _csv(self.cors_origins) or ["*"]

    @property
    def llm_chain(self) -> list[str]:
        return _csv(self.llm_providers)

    @property
    def stt_chain(self) -> list[str]:
        return _csv(self.stt_providers)

    def tts_chain(self, lang: str) -> list[str]:
        return _csv(getattr(self, f"tts_route_{lang}", "") or self.tts_route_en)

    def llm_credentials(self, name: str) -> tuple[str, str, str]:
        """(base_url, api_key, model) for an OpenAI-compatible LLM provider."""
        table = {
            "groq": (self.llm_groq_base_url, self.groq_api_key, self.llm_groq_model),
            "gemini": (self.llm_gemini_base_url, self.gemini_api_key, self.llm_gemini_model),
            "xai": (self.llm_xai_base_url, self.xai_api_key, self.llm_xai_model),
            # Ollama is local: no key needed, so it counts as "configured" always.
            "ollama": (self.llm_ollama_base_url, "ollama", self.llm_ollama_model),
        }
        if name not in table:
            raise KeyError(f"unknown LLM provider {name!r}")
        return table[name]

    @property
    def audio_path(self) -> Path:
        p = Path(self.audio_dir)
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@functools.lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.database_url.startswith("sqlite") and "/./var/" in s.database_url:
        (REPO_ROOT / "var").mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()

"""
Central configuration via pydantic-settings.
All values come from environment variables / .env file.
No secrets are hardcoded.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────
    app_name: str = "Addy Voice Agent"
    app_env: Literal["development", "production"] = "development"
    debug: bool = False

    # ── Security ──────────────────────────────────────────────────────────
    app_secret_key: SecretStr = Field(
        default=..., description="JWT signing key — change before deploying"
    )
    admin_username: str = "admin"
    admin_password: SecretStr = Field(default=...)
    access_token_expire_minutes: int = 60 * 24  # 24 hours

    # ── Identity ──────────────────────────────────────────────────────────
    agent_name: str = "Addy"
    user_name: str = "Adarsh"
    user_timezone: str = "Asia/Kolkata"

    # ── LLM ───────────────────────────────────────────────────────────────
    llm_provider: Literal["gemini", "groq", "luna"] = "gemini"
    llm_fallback_provider: Literal["gemini", "groq", "luna"] | None = "groq"

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_max_tokens: int = 1024

    groq_api_key: SecretStr | None = None
    groq_model_fast: str = "llama-3.1-8b-instant"      # Best for voice latency
    groq_model_smart: str = "llama-3.3-70b-versatile"  # For complex reasoning
    groq_max_tokens: int = 1024

    # ── Voice / STT ───────────────────────────────────────────────────────
    deepgram_api_key: SecretStr | None = None
    stt_model: str = "nova-3"
    stt_language: str = "multi"          # multilingual: handles Hindi/Hinglish
    stt_endpointing_ms: int = 300        # ms silence → utterance end
    stt_sample_rate: int = 16000
    stt_encoding: str = "webm/opus"

    # ── Voice / TTS ───────────────────────────────────────────────────────
    tts_model: str = "aura-2-asteria-en"
    tts_sample_rate: int = 24000
    tts_encoding: str = "linear16"

    # ── Voice session ─────────────────────────────────────────────────────
    # Max tokens agent may produce per turn (keeps voice responses short)
    voice_max_response_tokens: int = 300
    # How many recent messages to keep in context window
    context_window_messages: int = 20

    # ── Qdrant (ready for Phase 3, not used in Phase 1) ───────────────────
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333

    # ── Portfolio backend ─────────────────────────────────────────────────
    # URL of the portfolio FastAPI backend (for RAG and chatbot tools)
    portfolio_backend_url: str = "http://127.0.0.1:8000"

    # ── Hermes integration ────────────────────────────────────────────────
    hermes_url: str | None = None
    hermes_api_key: SecretStr | None = None
    hermes_timeout_s: int = 30
    # When True, use MockHermesClient (until real URL provided)
    hermes_mock: bool = True

    # ── Logging ───────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: Literal["json", "pretty"] = "pretty"

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "https://addy.adarshsingh.in",
    ]

    @field_validator("gemini_api_key", "groq_api_key", "deepgram_api_key", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    def get_llm_api_key(self, provider: str) -> str | None:
        """Return the decrypted API key for a given LLM provider."""
        mapping = {
            "gemini": self.gemini_api_key,
            "groq": self.groq_api_key,
        }
        secret = mapping.get(provider)
        return secret.get_secret_value() if secret else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

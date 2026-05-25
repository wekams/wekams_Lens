"""Environment-driven settings for Wekams Lens.

Single source of truth for runtime configuration. Anything that varies
between dev / staging / production / air-gap deployments must be a field
here — never read os.environ directly elsewhere.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(StrEnum):
    GROQ = "groq"
    OLLAMA = "ollama"


class Env(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────
    env: Env = Field(default=Env.DEVELOPMENT, alias="WEKAMS_ENV")
    log_level: str = Field(default="INFO", alias="WEKAMS_LOG_LEVEL")
    host: str = Field(default="0.0.0.0", alias="WEKAMS_HOST")
    port: int = Field(default=8000, alias="WEKAMS_PORT")

    # ── LLM ──────────────────────────────────────────────────────────
    llm_provider: LLMProvider = Field(
        default=LLMProvider.GROQ, alias="WEKAMS_LLM_PROVIDER"
    )

    # Provider-specific
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    llm_model_groq: str = Field(
        # qwen/qwen3-32b on Groq has reliable chat-completions-style tool calling and
        # matches the model family we ship in production (Qwen 2.5 / 3 series
        # via Ollama). llama-3.3-70b-versatile sometimes fails tool_use with
        # tool_use_failed 400s when multiple tools are exposed.
        default="qwen/qwen3-32b",
        alias="WEKAMS_LLM_MODEL_GROQ",
    )

    ollama_host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")
    llm_model_ollama: str = Field(
        default="qwen2.5:7b-instruct", alias="WEKAMS_LLM_MODEL_OLLAMA"
    )

    # ── Catalog DB ───────────────────────────────────────────────────
    catalog_db_url: str = Field(
        default="postgresql+asyncpg://wekams:wekams_dev@localhost:5432/wekams_catalog",
        alias="WEKAMS_CATALOG_DB_URL",
    )

    @property
    def is_air_gap_build(self) -> bool:
        """In air-gap production builds, only local LLM providers are allowed."""
        return self.env == Env.PRODUCTION and self.llm_provider in (
            LLMProvider.OLLAMA,
        )


settings = Settings()

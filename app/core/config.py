"""
app/core/config.py
------------------
Application settings loaded from environment variables / .env file.
All settings are validated by Pydantic at startup — a missing or
malformed value raises an error immediately, not at runtime.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration object — one instance for the entire app."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",          # silently ignore unknown env vars
    )

    # ------------------------------------------------------------------ #
    # Application                                                          #
    # ------------------------------------------------------------------ #
    APP_NAME: str = "SmartReco AI"
    APP_VERSION: str = "1.0.0"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False

    # ------------------------------------------------------------------ #
    # Server                                                               #
    # ------------------------------------------------------------------ #
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ------------------------------------------------------------------ #
    # Security                                                             #
    # ------------------------------------------------------------------ #
    SECRET_KEY: str = Field(default="change_me", min_length=8)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ------------------------------------------------------------------ #
    # CORS                                                                 #
    # ------------------------------------------------------------------ #
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    ALLOWED_METHODS: list[str] = ["*"]
    ALLOWED_HEADERS: list[str] = ["*"]
    ALLOW_CREDENTIALS: bool = True

    # ------------------------------------------------------------------ #
    # Database                                                             #
    # ------------------------------------------------------------------ #
    DATABASE_URL: str = Field(
        default="postgresql://postgres:password@localhost:5432/smartreco",
        description="Sync SQLAlchemy DSN (psycopg2).  "
                    "Use postgresql+asyncpg:// for async drivers.",
    )

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_db_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string.")
        return v

    # ------------------------------------------------------------------ #
    # Logging                                                              #
    # ------------------------------------------------------------------ #
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # ------------------------------------------------------------------ #
    # External services                                                    #
    # ------------------------------------------------------------------ #
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis DSN.")

    MESH_API_KEY: str = ""
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_TRACING: bool = Field(
        default=False,
        description="Set to true to enable LangSmith trace collection.",
    )
    LANGSMITH_PROJECT: str = Field(
        default="SmartReco-AI",
        description="LangSmith project name traces are sent to.",
    )

    # ------------------------------------------------------------------ #
    # LLM (OpenAI-compatible)                                              #
    # ------------------------------------------------------------------ #
    # LLM_API_KEY  : API key for your LLM provider (OpenAI, Together, etc.)
    # LLM_BASE_URL : Override for OpenAI-compatible endpoints; blank = OpenAI.
    # LLM_MODEL    : Model used for recommendation generation.
    LLM_API_KEY: str = Field(default="", description="LLM provider API key.")
    LLM_BASE_URL: str = Field(
        default="",
        description="OpenAI-compatible base URL. Leave blank for OpenAI default.",
    )
    LLM_MODEL: str = Field(
        default="minimax/m2-her",
        description="Model name for recommendation generation.",
    )

    # ------------------------------------------------------------------ #
    # Email (SMTP)                                                         #
    # ------------------------------------------------------------------ #
    EMAIL_ENABLED:   bool = Field(default=False, description="Enable email notifications.")
    SMTP_HOST:       str  = Field(default="",    description="SMTP server host.")
    SMTP_PORT:       int  = Field(default=587,   description="SMTP server port.")
    SMTP_USER:       str  = Field(default="",    description="SMTP login username.")
    SMTP_PASSWORD:   str  = Field(default="",    description="SMTP login password.")
    EMAIL_FROM:      str  = Field(default="",    description="From address e.g. 'SmartReco AI <you@gmail.com>'.")

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION: str = "products"

    # Vector store mode
    # - "qdrant"  → real Qdrant server (default; required for staging/production)
    # - "memory"  → in-process, zero-dependency (local dev / CI only;
    #               data is lost on restart — NOT for production)
    VECTOR_MODE: Literal["qdrant", "memory"] = "qdrant"

    # sentence-transformers embedding model
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSION: int = 384   # bge-small-en-v1.5 output dimension

    # ------------------------------------------------------------------ #
    # Computed helpers                                                     #
    # ------------------------------------------------------------------ #
    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the application settings singleton (cached after first call)."""
    return Settings()  # type: ignore[call-arg]


# Module-level shortcut — import this everywhere
settings: Settings = get_settings()

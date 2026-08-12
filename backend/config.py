"""
OrbitalMind — Application Settings
=====================================
Loads configuration from environment variables or a .env file using
pydantic-settings.  All settings have sensible defaults so the server
starts without a .env file during development.

Usage
-----
    from backend.config import settings

    if settings.DEMO_MODE:
        data = load_from_disk()
    else:
        data = run_live_inference()

.env file
---------
    Copy .env.example → .env and fill in your values.
    pydantic-settings automatically reads .env from the working directory.

Environment variable names are UPPER_CASE; pydantic-settings maps them
case-insensitively (DATABASE_URL, database_url, Database_Url all work).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the OrbitalMind platform.

    All fields can be overridden via environment variables or a .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",          # ignore unknown env vars (e.g. PATH, OS vars)
    )

    # ── Database ───────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/orbitalmind",
        description="SQLAlchemy 2.0 async DSN. Must use postgresql+asyncpg:// driver.",
    )

    # ── Demo mode ──────────────────────────────────────────────────────────
    DEMO_MODE: bool = Field(
        default=True,
        description=(
            "When True: all /analyze requests read from pre-computed demo data "
            "on disk (<200 ms). When False: runs live Sentinel-1 inference via "
            "FloodModule (only flood is production-ready in Phase 1)."
        ),
    )

    # ── Ollama / LLM ──────────────────────────────────────────────────────
    OLLAMA_URL: str = Field(
        default="http://localhost:11434",
        description="Base URL of the local Ollama server.",
    )
    OLLAMA_MODEL: str = Field(
        default="llama3.2:3b",
        description=(
            "Ollama model tag for LLM narration. "
            "VRAM NOTE: never run while FloodModule inference is active "
            "(RTX 3050 constraint)."
        ),
    )

    # ── Supported modules ──────────────────────────────────────────────────
    SUPPORTED_DISASTERS: list[str] = Field(
        default=["flood", "wildfire", "landslide", "cyclone", "earthquake"],
        description="Ordered list of active disaster module types.",
    )

    # ── API meta ───────────────────────────────────────────────────────────
    API_VERSION: str = Field(default="2.0.0")
    API_TITLE: str   = Field(default="OrbitalMind Platform API")

    # ── CORS ───────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        description="Allowed CORS origins. Add your production domain here.",
    )

    # ── Validators ─────────────────────────────────────────────────────────

    @field_validator("DATABASE_URL")
    @classmethod
    def normalise_db_url(cls, v: str) -> str:
        """Auto-convert postgresql:// → postgresql+asyncpg:// so users don't
        need to remember the driver suffix in their .env."""
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("SUPPORTED_DISASTERS")
    @classmethod
    def validate_disasters(cls, v: list[str]) -> list[str]:
        valid = {"flood", "wildfire", "landslide", "cyclone", "earthquake"}
        unknown = set(v) - valid
        if unknown:
            raise ValueError(f"Unknown disaster types: {unknown}. Valid: {valid}")
        return v

    @model_validator(mode="after")
    def validate_cors_origins(self) -> Settings:
        """Ensure CORS wildcard is not used when DEMO_MODE is False (production)."""
        if not self.DEMO_MODE and "*" in self.CORS_ORIGINS:
            raise ValueError(
                "CORS wildcard '*' is prohibited when DEMO_MODE=False (production mode). "
                "Specify explicit origin domains in CORS_ORIGINS setting."
            )
        return self

    # ── Convenience properties ─────────────────────────────────────────────

    @property
    def asyncpg_dsn(self) -> str:
        """DSN suitable for asyncpg.create_pool() — strips +asyncpg dialect."""
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def is_flood_live(self) -> bool:
        """True when live inference is enabled and flood module is in the list."""
        return not self.DEMO_MODE and "flood" in self.SUPPORTED_DISASTERS


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton.

    Using lru_cache means the .env file is read only once — not on every
    request.  Call ``get_settings.cache_clear()`` in tests to reset.
    """
    return Settings()


# Module-level singleton for direct import
settings: Settings = get_settings()

"""Settings (env-driven, no secrets in the repo)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GP_", env_file=None)

    database_url: str = "postgresql+psycopg://@/groundplan_dev?host=/tmp"
    dev_advisor_id: str = "00000000-0000-4000-8000-000000000001"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    retain_uploads_seconds: int = 0  # exists only to prove the point: bytes are never persisted
    max_upload_mb: int = 25
    llm_provider: str = ""  # "" (template) | anthropic | bedrock
    engine: str = "python"  # python | go (proxy to engine-go when it exists)
    engine_go_url: str = "http://localhost:8081"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

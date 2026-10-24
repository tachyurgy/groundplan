"""Settings (env-driven, no secrets in the repo)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GP_", env_file=None)

    database_url: str = "postgresql+psycopg://@/groundplan_dev?host=/tmp"
    dev_advisor_id: str = "00000000-0000-4000-8000-000000000001"
    cors_origins: list[str] = ["https://gp-python.levelbrook.com", "https://gp-go.levelbrook.com", "http://localhost:5173",
                               "http://localhost:4173", "http://127.0.0.1:5173"]
    cors_origin_regex: str = r"https://([a-z0-9-]+\.)?gp-(python|go)\.pages\.dev"
    retain_uploads_seconds: int = 0  # exists only to prove the point: bytes are never persisted
    max_upload_mb: int = 15
    max_body_mb: int = 20
    # SPEC §8.1 workspaces (no logins) and abuse guards
    max_workspaces_per_ip_per_day: int = 30
    max_households_per_workspace: int = 20
    max_documents_per_workspace: int = 50
    workspace_idle_days: int = 14
    sweep_interval_hours: float = 6.0
    sweep_enabled: bool = True
    git_sha: str = ""  # baked in at image build (GP_GIT_SHA); falls back to `git rev-parse`
    llm_provider: str = ""  # "" (template) | anthropic | bedrock
    engine: str = "python"  # python | go (forward engine computation to the Go service, fall back to Python on error)
    engine_go_url: str = "http://gp-go-api:8080"
    engine_go_timeout_s: float = 5.0
    pipeline_url: str = ""  # set -> POST {pipeline_url}/extract (the gp-pipeline service); unset -> gp_pipeline in-process
    pipeline_timeout_s: float = 120.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

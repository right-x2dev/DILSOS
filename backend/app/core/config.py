"""Application settings loaded from environment / .env (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "DILSOS"

    database_url: str = "sqlite:///./dilsos_dev.db"
    task_backend: Literal["celery", "db", "eager"] = "db"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me-dev-only-secret-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    demo_user_email: str = "demo@dilsos.local"
    demo_user_password: str = "demo1234"

    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    max_upload_bytes: int = 1_048_576
    max_solver_time_limit_s: int = 120
    run_timeout_s: int = 300

    @field_validator("database_url")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production and s.jwt_secret.startswith("change-me"):
        raise RuntimeError("JWT_SECRET must be set to a strong value in production")
    return s

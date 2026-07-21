"""Typed application configuration loaded from the environment."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "test", "staging", "production"]
AuthMode = Literal["development", "entra"]
LogFormat = Literal["json", "console"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="astra-licensing-automation", alias="APP_NAME")
    app_env: AppEnv = Field(default="local", alias="APP_ENV")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")

    database_url: str = Field(
        default="postgresql+asyncpg://astra:astra_local_dev@localhost:5442/astra_licensing",
        alias="DATABASE_URL",
    )
    database_pool_size: int = Field(default=5, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=10, alias="DATABASE_MAX_OVERFLOW")
    database_pool_recycle_seconds: int = Field(default=1800, alias="DATABASE_POOL_RECYCLE_SECONDS")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: LogFormat = Field(default="json", alias="LOG_FORMAT")
    sql_echo: bool = Field(default=False, alias="SQL_ECHO")

    cors_origins: list[str] = Field(default_factory=list, alias="CORS_ORIGINS")

    auth_mode: AuthMode = Field(default="development", alias="AUTH_MODE")

    prototype_import_root: str = Field(default="./prototype-data", alias="PROTOTYPE_IMPORT_ROOT")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _require_postgresql(cls, value: str) -> str:
        if not value.startswith(("postgresql+asyncpg://", "postgresql://")):
            raise ValueError("DATABASE_URL must point at PostgreSQL (postgresql+asyncpg://...)")
        return value

    @model_validator(mode="after")
    def _reject_unsafe_production_settings(self) -> Self:
        if self.app_env == "production":
            problems: list[str] = []
            if self.auth_mode == "development":
                problems.append("AUTH_MODE=development is not allowed in production")
            if self.sql_echo:
                problems.append("SQL_ECHO must be disabled in production")
            if "*" in self.cors_origins:
                problems.append("CORS_ORIGINS must not contain '*' in production")
            if problems:
                raise ValueError("; ".join(problems))
        return self

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

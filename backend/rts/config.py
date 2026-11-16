"""Application settings loaded from environment variables (prefix ``RTS_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RTS_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path("./data"))
    database_url: str | None = None
    secret_key: str | None = None
    default_timezone: str = "America/Sao_Paulo"
    auto_migrate: bool = True
    log_level: str = "INFO"

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'rts.db').as_posix()}"

    @property
    def secret_key_file(self) -> Path:
        return self.data_dir / "secret.key"

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()

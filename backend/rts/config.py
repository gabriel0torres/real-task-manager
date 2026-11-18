"""Application settings loaded from environment variables (prefix ``RTS_``)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RTS_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path("./data"))
    # Where `rts api` / `rts start` listen.
    host: str = "0.0.0.0"
    port: int = 8000
    database_url: str | None = None
    secret_key: str | None = None
    default_timezone: str = "America/Sao_Paulo"
    auto_migrate: bool = True
    log_level: str = "INFO"
    # Run the scheduling engine inside the API process (dev / single-process setups).
    embedded_worker: bool = False
    # Max bytes of log stored per run; output beyond this is dropped (with a notice).
    max_log_bytes: int = 5_000_000
    # Seconds a scheduled fire may be late before the missed-run policy applies.
    misfire_grace_seconds: int = 60

    # Authentication. The admin user is created on first start; if no password is
    # given a random one is generated, printed in the log and must be changed.
    admin_username: str = "admin"
    admin_password: str | None = None
    session_ttl_hours: int = 24 * 7
    # Set to true when the UI is served over HTTPS.
    cookie_secure: bool = False

    # Public base URL of the UI, used for links in notifications (optional).
    public_url: str | None = None
    # Built frontend (Vite "dist") served by the API, if present.
    frontend_dir: Path | None = None

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @property
    def effective_frontend_dir(self) -> Path | None:
        if self.frontend_dir is not None:
            return self.frontend_dir if (self.frontend_dir / "index.html").exists() else None
        candidates = [
            # Release packages (wheel / standalone executable) ship the built UI here.
            Path(__file__).resolve().parent / "web",
            # Development checkout: <repo>/frontend/dist
            Path(__file__).resolve().parents[2] / "frontend" / "dist",
        ]
        return next((c for c in candidates if (c / "index.html").exists()), None)

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

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    # RTS_ENV_FILE lets services point at the installation's configuration file.
    return Settings(_env_file=os.environ.get("RTS_ENV_FILE", ".env"))

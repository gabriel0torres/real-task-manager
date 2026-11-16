"""System-level tables: key/value settings and worker heartbeat."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from rts.db import Base
from rts.models.base import UTCDateTime, utcnow


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeat"

    worker_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from rts.config import Settings
from rts.security.crypto import SecretBox


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class EngineContext:
    settings: Settings
    session_factory: sessionmaker[Session]
    secret_box: SecretBox
    clock: Callable[[], datetime] = field(default=_utcnow)

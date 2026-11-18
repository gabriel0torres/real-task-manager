from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from rts.config import Settings
from rts.security.crypto import SecretBox


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RunListener(Protocol):
    def notify_run(self, run_id: int) -> None: ...


@dataclass
class EngineContext:
    settings: Settings
    session_factory: sessionmaker[Session]
    secret_box: SecretBox
    clock: Callable[[], datetime] = field(default=_utcnow)
    # Called when a run reaches a final state (notifications).
    notifier: RunListener | None = None

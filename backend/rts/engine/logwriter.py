"""Buffered, masked writer of run log chunks."""

from __future__ import annotations

import threading

from sqlalchemy.orm import Session, sessionmaker

from rts.models import LogStream, RunLogChunk
from rts.models.base import utcnow
from rts.security.masking import SecretMasker
from rts.services.runs import SYSTEM_PREFIX, next_log_seq


class LogWriter:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        run_id: int,
        masker: SecretMasker,
        max_bytes: int,
    ) -> None:
        self._factory = session_factory
        self._run_id = run_id
        self._masker = masker
        self._max_bytes = max_bytes
        self._pending: list[tuple[LogStream, str]] = []
        self._written_bytes = 0
        self._truncated = False
        self._seq: int | None = None
        self._lock = threading.Lock()

    def write(self, stream: LogStream, text: str) -> None:
        if not text:
            return
        with self._lock:
            if self._truncated:
                return
            text = self._masker.mask(text.replace("\r\n", "\n"))
            remaining = self._max_bytes - self._written_bytes
            if len(text) > remaining:
                text = text[: max(remaining, 0)]
                self._truncated = True
            self._written_bytes += len(text)
            if text:
                self._pending.append((stream, text))
            if self._truncated:
                limit_mb = self._max_bytes / 1_000_000
                self._pending.append(
                    (
                        LogStream.SYSTEM,
                        f"\n{SYSTEM_PREFIX}Log truncado: limite de {limit_mb:g} MB atingido.\n",
                    )
                )

    def system(self, message: str) -> None:
        """System messages bypass the size limit (but are still masked)."""
        with self._lock:
            self._pending.append(
                (LogStream.SYSTEM, self._masker.mask(f"{SYSTEM_PREFIX}{message}\n"))
            )

    def flush(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, []
        if not pending:
            return
        merged: list[tuple[LogStream, str]] = []
        for stream, text in pending:
            if merged and merged[-1][0] is stream:
                merged[-1] = (stream, merged[-1][1] + text)
            else:
                merged.append((stream, text))
        with self._factory() as session:
            if self._seq is None:
                self._seq = next_log_seq(session, self._run_id) - 1
            now = utcnow()
            for stream, text in merged:
                self._seq += 1
                session.add(
                    RunLogChunk(
                        run_id=self._run_id, seq=self._seq, ts=now, stream=stream, content=text
                    )
                )
            session.commit()

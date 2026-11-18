"""Task executions and their logs."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rts.db import Base
from rts.models.base import UTCDateTime, str_enum, utcnow
from rts.models.enums import LogStream, RunStatus, RunTrigger, SequenceStatus

if TYPE_CHECKING:
    from rts.models.hierarchy import Subcategory, Task


class SequenceRun(Base):
    """One run of a sequential subcategory: its tasks, one after the other.

    The task list is frozen when the sequence starts (``task_ids``, in order). Each
    step is a normal :class:`Run` linked by ``sequence_run_id``/``sequence_index``;
    the engine starts the next step once the current one is settled (retries included).
    """

    __tablename__ = "sequence_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    subcategory_id: Mapped[int] = mapped_column(
        ForeignKey("subcategories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[SequenceStatus] = mapped_column(
        str_enum(SequenceStatus, "sequence_status"), default=SequenceStatus.RUNNING, nullable=False
    )
    trigger: Mapped[RunTrigger] = mapped_column(
        str_enum(RunTrigger, "sequence_trigger"), nullable=False
    )
    triggered_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    task_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    current_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stop_on_failure: Mapped[bool] = mapped_column(default=False, nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    subcategory: Mapped[Subcategory] = relationship()
    runs: Mapped[list[Run]] = relationship(
        back_populates="sequence_run", order_by="Run.id", passive_deletes=True
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        str_enum(RunStatus, "run_status"), default=RunStatus.PENDING, nullable=False
    )
    trigger: Mapped[RunTrigger] = mapped_column(str_enum(RunTrigger, "run_trigger"), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # First attempt of a retry chain (NULL on the first attempt itself).
    root_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    scheduled_for: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(default=False, nullable=False)
    triggered_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Step of a sequential subcategory run (index into SequenceRun.task_ids).
    sequence_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sequence_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sequence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    task: Mapped[Task] = relationship(back_populates="runs")
    sequence_run: Mapped[SequenceRun | None] = relationship(back_populates="runs")
    log_chunks: Mapped[list[RunLogChunk]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="RunLogChunk.seq"
    )

    __table_args__ = (
        Index("ix_runs_task_created", "task_id", "created_at"),
        Index("ix_runs_status", "status"),
    )


class RunLogChunk(Base):
    """Append-only, already-masked piece of a run log (streamed to the UI)."""

    __tablename__ = "run_log_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    stream: Mapped[LogStream] = mapped_column(str_enum(LogStream, "log_stream"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("ix_run_log_chunks_run_seq", "run_id", "seq", unique=True),)

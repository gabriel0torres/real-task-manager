"""Run lifecycle helpers shared by the API and the engine."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from rts.models import LogStream, Run, RunLogChunk, RunStatus, RunTrigger
from rts.models.base import utcnow
from rts.models.enums import FINAL_RUN_STATUSES
from rts.services.errors import ConflictError, NotFoundError
from rts.services.hierarchy import get_task

SYSTEM_PREFIX = "[RTS] "


def next_log_seq(session: Session, run_id: int) -> int:
    current = session.scalar(select(func.max(RunLogChunk.seq)).where(RunLogChunk.run_id == run_id))
    return (current or 0) + 1


def append_system_log(session: Session, run_id: int, message: str) -> None:
    session.add(
        RunLogChunk(
            run_id=run_id,
            seq=next_log_seq(session, run_id),
            stream=LogStream.SYSTEM,
            content=f"{SYSTEM_PREFIX}{message}\n",
        )
    )


def finish_without_running(
    session: Session, run: Run, status: RunStatus, reason: str, now: datetime | None = None
) -> None:
    """Close a run that never started (skipped, cancelled while pending...)."""
    run.status = status
    run.status_reason = reason
    run.finished_at = now or utcnow()
    append_system_log(session, run.id, reason)


def create_run(
    session: Session,
    task_id: int,
    trigger: RunTrigger,
    *,
    scheduled_for: datetime | None = None,
    triggered_by: str | None = None,
    attempt: int = 1,
    root_run_id: int | None = None,
) -> Run:
    run = Run(
        task_id=task_id,
        trigger=trigger,
        status=RunStatus.PENDING,
        scheduled_for=scheduled_for,
        triggered_by=triggered_by,
        attempt=attempt,
        root_run_id=root_run_id,
    )
    session.add(run)
    session.flush()
    return run


def request_manual_run(
    session: Session, task_id: int, trigger: RunTrigger = RunTrigger.MANUAL, by: str | None = None
) -> Run:
    get_task(session, task_id)
    return create_run(session, task_id, trigger, triggered_by=by)


def get_run(session: Session, run_id: int) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise NotFoundError(f"Execução {run_id} não encontrada.")
    return run


def cancel_run(session: Session, run_id: int) -> Run:
    run = get_run(session, run_id)
    if run.status in FINAL_RUN_STATUSES:
        raise ConflictError("A execução já terminou.")
    if run.status is RunStatus.PENDING:
        finish_without_running(session, run, RunStatus.CANCELLED, "Cancelada antes de iniciar.")
    else:
        # The executor polls this flag and kills the process tree.
        run.cancel_requested = True
    session.flush()
    return run


def list_runs(
    session: Session,
    *,
    task_id: int | None = None,
    statuses: list[RunStatus] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Run], int]:
    conds = []
    if task_id is not None:
        conds.append(Run.task_id == task_id)
    if statuses:
        conds.append(Run.status.in_(statuses))
    if since is not None:
        conds.append(Run.created_at >= since)
    if until is not None:
        conds.append(Run.created_at <= until)
    total = session.scalar(select(func.count(Run.id)).where(*conds)) or 0
    stmt = (
        select(Run)
        .options(selectinload(Run.task))
        .where(*conds)
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt)), total


def get_log_chunks(session: Session, run_id: int, after_seq: int = 0) -> list[RunLogChunk]:
    stmt = (
        select(RunLogChunk)
        .where(RunLogChunk.run_id == run_id, RunLogChunk.seq > after_seq)
        .order_by(RunLogChunk.seq)
    )
    return list(session.scalars(stmt))

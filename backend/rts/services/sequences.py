"""Sequential subcategories: their tasks run one after the other.

A :class:`SequenceRun` freezes the ordered task list when it starts. Each step is a
normal run (logs, timeout, retries, notifications work as usual), linked to the
sequence. The engine calls :func:`advance_sequences` on every tick: once the current
step is *settled* (finished and with no retry waiting), it starts the next one, or
stops the sequence at a failure when ``stop_on_failure`` is set.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from rts.models import (
    Run,
    RunStatus,
    RunTrigger,
    SequenceRun,
    SequenceStatus,
    Subcategory,
    Task,
)
from rts.models.base import utcnow
from rts.services.errors import ConflictError, InvalidInputError, NotFoundError
from rts.services.runs import append_system_log, cancel_run, create_run

SKIPPED_BUSY = "Pulada: a sequência anterior desta subcategoria ainda está em andamento."
SKIPPED_EMPTY = "Pulada: nenhuma tarefa ativa com a origem de agendamento “Herdar”."
STATUS_LABELS = {
    RunStatus.SUCCESS: "sucesso",
    RunStatus.FAILED: "falha",
    RunStatus.TIMEOUT: "tempo esgotado",
    RunStatus.CANCELLED: "cancelada",
    RunStatus.SKIPPED: "pulada",
}
_ACTIVE = (RunStatus.PENDING, RunStatus.RUNNING)


def running_sequence(session: Session, subcategory_id: int) -> SequenceRun | None:
    return session.scalars(
        select(SequenceRun).where(
            SequenceRun.subcategory_id == subcategory_id,
            SequenceRun.status == SequenceStatus.RUNNING,
        )
    ).first()


def _finish(seq: SequenceRun, status: SequenceStatus, reason: str | None, now: datetime) -> None:
    seq.status = status
    seq.status_reason = reason
    seq.finished_at = now


def _step_task(session: Session, seq: SequenceRun, index: int) -> Task | None:
    task = session.get(Task, seq.task_ids[index])
    return task if task is not None and task.is_active else None


def _start_step(session: Session, seq: SequenceRun, index: int) -> Run:
    seq.current_index = index
    run = create_run(
        session,
        seq.task_ids[index],
        seq.trigger,
        scheduled_for=seq.scheduled_for,
        triggered_by=seq.triggered_by,
        sequence_run_id=seq.id,
        sequence_index=index,
    )
    append_system_log(
        session,
        run.id,
        f"Etapa {index + 1} de {len(seq.task_ids)} da sequência #{seq.id} "
        f"(subcategoria '{seq.subcategory.name}').",
    )
    return run


def _next_index(session: Session, seq: SequenceRun, after: int) -> int | None:
    """Next step whose task still exists and is active (others are passed over)."""
    for index in range(after + 1, len(seq.task_ids)):
        if _step_task(session, seq, index) is not None:
            return index
    return None


def start_sequence(
    session: Session,
    sub: Subcategory,
    trigger: RunTrigger,
    *,
    scheduled_for: datetime | None = None,
    triggered_by: str | None = None,
    now: datetime | None = None,
) -> SequenceRun:
    """Start a sequence (or record it as skipped). The caller commits."""
    now = now or utcnow()
    busy = running_sequence(session, sub.id) is not None
    tasks = sub.sequence_tasks()
    seq = SequenceRun(
        subcategory_id=sub.id,
        status=SequenceStatus.RUNNING,
        trigger=trigger,
        triggered_by=triggered_by,
        task_ids=[t.id for t in tasks],
        current_index=0,
        stop_on_failure=sub.stop_on_failure,
        scheduled_for=scheduled_for,
        created_at=now,
    )
    seq.subcategory = sub
    session.add(seq)
    if busy:
        _finish(seq, SequenceStatus.SKIPPED, SKIPPED_BUSY, now)
    elif not tasks:
        _finish(seq, SequenceStatus.SKIPPED, SKIPPED_EMPTY, now)
    session.flush()
    if seq.status is SequenceStatus.RUNNING:
        _start_step(session, seq, 0)
    return seq


def advance_sequences(session: Session, now: datetime | None = None) -> bool:
    """Move every running sequence forward. Returns True when something changed."""
    now = now or utcnow()
    changed = False
    running = session.scalars(
        select(SequenceRun)
        .options(selectinload(SequenceRun.runs), selectinload(SequenceRun.subcategory))
        .where(SequenceRun.status == SequenceStatus.RUNNING)
    ).all()
    for seq in running:
        step_runs = [r for r in seq.runs if r.sequence_index == seq.current_index]
        if not step_runs:
            # The step's run was deleted (e.g. its task): go on with the next one.
            last_status = RunStatus.CANCELLED
        elif any(r.status in _ACTIVE for r in step_runs):
            continue  # running, queued or waiting for a retry
        else:
            last_status = max(step_runs, key=lambda r: r.id).status
        changed = True
        if last_status is not RunStatus.SUCCESS and seq.stop_on_failure:
            task = session.get(Task, seq.task_ids[seq.current_index])
            name = task.name if task else f"tarefa {seq.task_ids[seq.current_index]}"
            _finish(
                seq,
                SequenceStatus.FAILED,
                f"Parou na etapa {seq.current_index + 1} ({name}): "
                f"{STATUS_LABELS.get(last_status, last_status.value)}.",
                now,
            )
            continue
        nxt = _next_index(session, seq, seq.current_index)
        if nxt is not None:
            _start_step(session, seq, nxt)
            continue
        _finish(seq, *_outcome(seq), now)
    if changed:
        session.flush()
    return changed


def _last_runs(seq: SequenceRun) -> dict[int, Run]:
    """Step index -> its latest run (the last attempt when there were retries)."""
    last: dict[int, Run] = {}
    for run in seq.runs:
        index = run.sequence_index
        if index is not None and (index not in last or run.id > last[index].id):
            last[index] = run
    return last


def _outcome(seq: SequenceRun) -> tuple[SequenceStatus, str]:
    total = len(seq.task_ids)
    last = _last_runs(seq)
    ok = sum(1 for r in last.values() if r.status is RunStatus.SUCCESS)
    if ok == total:
        return SequenceStatus.SUCCESS, f"{total} de {total} tarefas com sucesso."
    return SequenceStatus.FAILED, f"{ok} de {total} tarefas com sucesso."


def get_sequence(session: Session, sequence_id: int) -> SequenceRun:
    seq = session.get(SequenceRun, sequence_id)
    if seq is None:
        raise NotFoundError(f"Sequência {sequence_id} não encontrada.")
    return seq


def request_sequence(session: Session, sub: Subcategory, by: str | None = None) -> SequenceRun:
    """ "Executar sequência agora" (works even if the subcategory is paused)."""
    if not sub.is_sequential:
        raise InvalidInputError("A subcategoria não está no modo sequencial.")
    if running_sequence(session, sub.id) is not None:
        raise ConflictError("Já existe uma sequência em andamento nesta subcategoria.")
    seq = start_sequence(session, sub, RunTrigger.MANUAL, triggered_by=by)
    if seq.status is SequenceStatus.SKIPPED:
        raise InvalidInputError(seq.status_reason or "Nada a executar.")
    return seq


def cancel_sequence(session: Session, sequence_id: int) -> SequenceRun:
    seq = get_sequence(session, sequence_id)
    if seq.status is not SequenceStatus.RUNNING:
        raise ConflictError("A sequência já terminou.")
    _finish(seq, SequenceStatus.CANCELLED, "Cancelada pelo usuário.", utcnow())
    for run in seq.runs:
        if run.status in _ACTIVE:
            cancel_run(session, run.id)
    session.flush()
    return seq


def list_sequences(session: Session, subcategory_id: int, limit: int = 20) -> list[SequenceRun]:
    stmt = (
        select(SequenceRun)
        .options(selectinload(SequenceRun.runs).selectinload(Run.task))
        .where(SequenceRun.subcategory_id == subcategory_id)
        .order_by(SequenceRun.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def sequence_to_out(session: Session, seq: SequenceRun) -> dict:
    """Steps with their latest run (retries collapse into the last attempt)."""
    last = _last_runs(seq)
    names = {
        t.id: t.name for t in session.scalars(select(Task).where(Task.id.in_(seq.task_ids or [-1])))
    }
    steps = []
    for index, task_id in enumerate(seq.task_ids):
        run = last.get(index)
        steps.append(
            {
                "index": index,
                "task_id": task_id,
                "task_name": names.get(task_id, f"tarefa {task_id} (excluída)"),
                "run_id": run.id if run else None,
                "status": run.status.value if run else "not_run",
                "attempt": run.attempt if run else None,
                "started_at": run.started_at if run else None,
                "finished_at": run.finished_at if run else None,
                "duration_ms": run.duration_ms if run else None,
            }
        )
    done = sum(1 for s in steps if s["status"] not in ("not_run", "pending", "running"))
    return {
        "id": seq.id,
        "subcategory_id": seq.subcategory_id,
        "status": seq.status.value,
        "trigger": seq.trigger.value,
        "triggered_by": seq.triggered_by,
        "stop_on_failure": seq.stop_on_failure,
        "scheduled_for": seq.scheduled_for,
        "created_at": seq.created_at,
        "finished_at": seq.finished_at,
        "status_reason": seq.status_reason,
        "current_index": seq.current_index,
        "total_steps": len(seq.task_ids),
        "completed_steps": done,
        "steps": steps,
    }

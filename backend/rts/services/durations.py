"""How long a group's automations take, per subcategory.

* Sequential subcategory: one entry per sequence run (start of the first step to
  the end of the sequence).
* Parallel subcategory: one entry per *round*, i.e. the scheduled runs fired at the
  same time (with their retries): from the first start to the last finish.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from rts.models import Run, RunStatus, RunTrigger, SequenceRun, SequenceStatus, Subcategory
from rts.models.enums import FINAL_RUN_STATUSES
from rts.services.hierarchy import get_group, list_subcategories
from rts.services.sequences import group_activity, latest_step_runs

AVERAGE_OF = 10


def _ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def _entry(kind: str, ident, started, finished, status: str, succeeded: int, total: int) -> dict:
    return {
        "kind": kind,
        "sequence_id": ident,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": _ms(started, finished),
        "status": status,
        "succeeded": succeeded,
        "total": total,
    }


def _sequence_entries(session: Session, sub: Subcategory) -> list[dict]:
    seqs = session.scalars(
        select(SequenceRun)
        .options(selectinload(SequenceRun.runs))
        .where(
            SequenceRun.subcategory_id == sub.id,
            SequenceRun.status != SequenceStatus.SKIPPED,
        )
        .order_by(SequenceRun.id.desc())
        .limit(AVERAGE_OF + 1)
    ).all()
    entries = []
    for seq in seqs:
        starts = [r.started_at for r in seq.runs if r.started_at is not None]
        started = min(starts) if starts else seq.created_at
        last = latest_step_runs(seq)
        ok = sum(1 for r in last.values() if r.status is RunStatus.SUCCESS)
        entries.append(
            _entry(
                "sequence",
                seq.id,
                started,
                seq.finished_at,
                seq.status.value,
                ok,
                len(seq.task_ids),
            )
        )
    return entries


def _round_entries(session: Session, sub: Subcategory) -> list[dict]:
    task_ids = [t.id for t in sub.tasks]
    if not task_ids:
        return []
    scheduled = (
        Run.task_id.in_(task_ids),
        Run.trigger == RunTrigger.SCHEDULED,
        Run.sequence_run_id.is_(None),
        Run.scheduled_for.is_not(None),
    )
    times = session.scalars(
        select(Run.scheduled_for)
        .where(*scheduled)
        .group_by(Run.scheduled_for)
        .order_by(Run.scheduled_for.desc())
        .limit(AVERAGE_OF + 1)
    ).all()
    entries = []
    for when in times:
        firsts = session.scalars(select(Run).where(*scheduled, Run.scheduled_for == when)).all()
        retries = session.scalars(
            select(Run).where(Run.root_run_id.in_([r.id for r in firsts]))
        ).all()
        runs = [*firsts, *retries]
        # Outcome of each task in the round: its latest attempt.
        latest: dict[int, Run] = {}
        for run in runs:
            root = run.root_run_id or run.id
            if root not in latest or run.id > latest[root].id:
                latest[root] = run
        done = all(r.status in FINAL_RUN_STATUSES for r in runs)
        ok = sum(1 for r in latest.values() if r.status is RunStatus.SUCCESS)
        starts = [r.started_at for r in runs if r.started_at is not None]
        ends = [r.finished_at for r in runs if r.finished_at is not None]
        status = "running" if not done else ("success" if ok == len(latest) else "failed")
        entries.append(
            _entry(
                "round",
                None,
                min(starts) if starts else when,
                max(ends) if done and ends else None,
                status,
                ok,
                len(latest),
            )
        )
    return entries


def group_execution_times(session: Session, group_id: int) -> dict:
    get_group(session, group_id)
    rows = []
    for sub in list_subcategories(session, group_id):
        entries = (
            _sequence_entries(session, sub) if sub.is_sequential else _round_entries(session, sub)
        )
        running = next((e for e in entries if e["status"] == "running"), None)
        finished = [e for e in entries if e["status"] != "running" and e["duration_ms"] is not None]
        # The average leaves out cancelled runs (they say nothing about the usual time).
        sample = [e["duration_ms"] for e in finished if e["status"] != "cancelled"][:AVERAGE_OF]
        rows.append(
            {
                "subcategory_id": sub.id,
                "name": sub.name,
                "execution_mode": sub.execution_mode.value,
                "running": running,
                "last": finished[0] if finished else None,
                "average_ms": int(sum(sample) / len(sample)) if sample else None,
                "average_of": len(sample),
            }
        )
    total = sum(r["last"]["duration_ms"] for r in rows if r["last"])
    return {
        "group_id": group_id,
        "subcategories": rows,
        "total_last_ms": total,
        "activity": group_activity(session, group_id),
    }

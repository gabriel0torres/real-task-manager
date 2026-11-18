"""Read models for the navigation tree and the dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from rts.models import Group, Run, RunStatus, Subcategory, Task
from rts.models.base import utcnow
from rts.scheduling.cron import CronError, next_fire_times

# Statuses that count as "the last result" of a task (skips/cancels don't).
RESULT_STATUSES = (RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.TIMEOUT)
FAILURE_STATUSES = (RunStatus.FAILED, RunStatus.TIMEOUT)


def _last_results(session: Session) -> dict[int, Run]:
    latest = (
        select(func.max(Run.id).label("id"))
        .where(Run.status.in_(RESULT_STATUSES))
        .group_by(Run.task_id)
        .subquery()
    )
    runs = session.scalars(select(Run).join(latest, Run.id == latest.c.id))
    return {r.task_id: r for r in runs}


def _running_task_ids(session: Session) -> set[int]:
    return set(session.scalars(select(Run.task_id).where(Run.status == RunStatus.RUNNING)))


def build_tree(session: Session) -> list[dict]:
    groups = session.scalars(
        select(Group)
        .options(selectinload(Group.subcategories).selectinload(Subcategory.tasks))
        .order_by(func.lower(Group.name))
    ).all()
    last = _last_results(session)
    running = _running_task_ids(session)

    tree = []
    for g in groups:
        subs = []
        for s in g.subcategories:
            tasks = []
            for t in s.tasks:
                lr = last.get(t.id)
                tasks.append(
                    {
                        "id": t.id,
                        "name": t.name,
                        "is_active": t.is_active,
                        "is_effectively_active": t.is_active and s.is_active and g.is_active,
                        "running": t.id in running,
                        "last_run_status": lr.status if lr else None,
                        "last_run_at": lr.finished_at if lr else None,
                    }
                )
            subs.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "is_active": s.is_active,
                    "is_effectively_active": s.is_active and g.is_active,
                    "has_failure": any(t["last_run_status"] in FAILURE_STATUSES for t in tasks),
                    "tasks": tasks,
                }
            )
        tree.append(
            {
                "id": g.id,
                "name": g.name,
                "is_active": g.is_active,
                "has_failure": any(s["has_failure"] for s in subs),
                "subcategories": subs,
            }
        )
    return tree


def _period_stats(session: Session, since: datetime) -> dict:
    rows = session.execute(
        select(Run.status, func.count(Run.id))
        .where(Run.created_at >= since, Run.status.in_(RESULT_STATUSES))
        .group_by(Run.status)
    ).all()
    counts = {status: n for status, n in rows}
    success = counts.get(RunStatus.SUCCESS, 0)
    failed = counts.get(RunStatus.FAILED, 0)
    timeout = counts.get(RunStatus.TIMEOUT, 0)
    total = success + failed + timeout
    return {
        "success": success,
        "failed": failed,
        "timeout": timeout,
        "total": total,
        "success_rate": round(success / total, 4) if total else None,
    }


def upcoming_runs(session: Session, default_tz: str, limit: int = 10) -> list[dict]:
    tasks = session.scalars(
        select(Task).options(selectinload(Task.subcategory).selectinload(Subcategory.group))
    ).all()
    items = []
    for t in tasks:
        if not t.cron_expressions or not t.is_effectively_active:
            continue
        try:
            fires = next_fire_times(t.cron_expressions, t.timezone or default_tz, 3)
        except CronError:
            continue
        items.extend(
            {
                "task_id": t.id,
                "task_name": t.name,
                "subcategory_name": t.subcategory.name,
                "group_name": t.subcategory.group.name,
                "at": at,
            }
            for at in fires
        )
    items.sort(key=lambda i: i["at"])
    return items[:limit]


def dashboard_data(session: Session, default_tz: str) -> dict:
    now = utcnow()
    running = session.scalars(
        select(Run)
        .options(selectinload(Run.task))
        .where(Run.status == RunStatus.RUNNING)
        .order_by(Run.started_at)
    ).all()
    failures = session.scalars(
        select(Run)
        .options(selectinload(Run.task))
        .where(Run.status.in_(FAILURE_STATUSES))
        .order_by(Run.id.desc())
        .limit(10)
    ).all()
    task_total = session.scalar(select(func.count(Task.id))) or 0
    tasks = session.scalars(
        select(Task).options(selectinload(Task.subcategory).selectinload(Subcategory.group))
    ).all()
    active = sum(1 for t in tasks if t.is_effectively_active)
    return {
        "running": running,
        "recent_failures": failures,
        "upcoming": upcoming_runs(session, default_tz),
        "stats": {
            "last_24h": _period_stats(session, now - timedelta(hours=24)),
            "last_7d": _period_stats(session, now - timedelta(days=7)),
        },
        "counts": {
            "groups": session.scalar(select(func.count(Group.id))) or 0,
            "subcategories": session.scalar(select(func.count(Subcategory.id))) or 0,
            "tasks": task_total,
            "tasks_active": active,
            "tasks_paused": task_total - active,
        },
    }

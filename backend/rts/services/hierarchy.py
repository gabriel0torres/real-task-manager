"""CRUD for groups, subcategories and tasks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session, selectinload

from rts.models import EffectiveSchedule, Group, ScheduleMode, Subcategory, Task
from rts.scheduling.cron import CronError, next_fire_times
from rts.scheduling.describe import describe
from rts.schemas.hierarchy import (
    GroupCreate,
    GroupOut,
    GroupUpdate,
    InheritedScheduleOut,
    SubcategoryCreate,
    SubcategoryOut,
    SubcategoryUpdate,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)
from rts.services.errors import ConflictError, InvalidInputError, NotFoundError
from rts.services.settings import bump_config_revision

TASK_NULLABLE_FIELDS = {"shell", "working_dir", "timezone", "timeout_seconds"}
OWNER_NULLABLE_FIELDS = {"timezone"}
OWN_SCHEDULE_REQUIRED = (
    "Informe pelo menos uma expressão cron para o agendamento próprio "
    "(ou escolha herdar ou somente manual)."
)


def _apply(obj: Any, changes: dict[str, Any], nullable: set[str] = frozenset()) -> None:
    for field, value in changes.items():
        if value is None and field not in nullable:
            raise InvalidInputError(f"O campo '{field}' não pode ser nulo.")
        setattr(obj, field, value)


# --------------------------------------------------------------------------- groups
def list_groups(session: Session) -> list[Group]:
    return list(session.scalars(select(Group).order_by(func.lower(Group.name))))


def get_group(session: Session, group_id: int) -> Group:
    group = session.get(Group, group_id)
    if group is None:
        raise NotFoundError(f"Grupo {group_id} não encontrado.")
    return group


def _ensure_group_name_free(session: Session, name: str, exclude_id: int | None = None) -> None:
    stmt = select(Group.id).where(func.lower(Group.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Group.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ConflictError(f"Já existe um grupo chamado '{name}'.")


def create_group(session: Session, data: GroupCreate) -> Group:
    _ensure_group_name_free(session, data.name)
    group = Group(**data.model_dump())
    session.add(group)
    bump_config_revision(session)
    session.flush()
    return group


def update_group(session: Session, group_id: int, data: GroupUpdate) -> Group:
    group = get_group(session, group_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        _ensure_group_name_free(session, changes["name"], exclude_id=group.id)
    _apply(group, changes, OWNER_NULLABLE_FIELDS)
    bump_config_revision(session)
    session.flush()
    return group


def delete_group(session: Session, group_id: int) -> None:
    session.delete(get_group(session, group_id))
    bump_config_revision(session)
    session.flush()


# --------------------------------------------------------------------------- subcategories
def list_subcategories(session: Session, group_id: int | None = None) -> list[Subcategory]:
    stmt = select(Subcategory).options(selectinload(Subcategory.group))
    if group_id is not None:
        stmt = stmt.where(Subcategory.group_id == group_id)
    return list(session.scalars(stmt.order_by(func.lower(Subcategory.name))))


def get_subcategory(session: Session, subcategory_id: int) -> Subcategory:
    sub = session.get(Subcategory, subcategory_id)
    if sub is None:
        raise NotFoundError(f"Subcategoria {subcategory_id} não encontrada.")
    return sub


def _ensure_subcategory_name_free(
    session: Session, group_id: int, name: str, exclude_id: int | None = None
) -> None:
    stmt = select(Subcategory.id).where(
        Subcategory.group_id == group_id, func.lower(Subcategory.name) == name.lower()
    )
    if exclude_id is not None:
        stmt = stmt.where(Subcategory.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ConflictError(f"Já existe uma subcategoria '{name}' neste grupo.")


def create_subcategory(session: Session, data: SubcategoryCreate) -> Subcategory:
    get_group(session, data.group_id)
    _ensure_subcategory_name_free(session, data.group_id, data.name)
    sub = Subcategory(**data.model_dump())
    session.add(sub)
    bump_config_revision(session)
    session.flush()
    return sub


def update_subcategory(
    session: Session, subcategory_id: int, data: SubcategoryUpdate
) -> Subcategory:
    sub = get_subcategory(session, subcategory_id)
    changes = data.model_dump(exclude_unset=True)
    target_group = changes.get("group_id") or sub.group_id
    if "group_id" in changes and changes["group_id"] is not None:
        get_group(session, changes["group_id"])
    target_name = changes.get("name") or sub.name
    if "name" in changes or "group_id" in changes:
        _ensure_subcategory_name_free(session, target_group, target_name, exclude_id=sub.id)
    _apply(sub, changes, OWNER_NULLABLE_FIELDS)
    bump_config_revision(session)
    session.flush()
    session.refresh(sub)
    return sub


def delete_subcategory(session: Session, subcategory_id: int) -> None:
    session.delete(get_subcategory(session, subcategory_id))
    bump_config_revision(session)
    session.flush()


# --------------------------------------------------------------------------- tasks
def list_tasks(
    session: Session, subcategory_id: int | None = None, group_id: int | None = None
) -> list[Task]:
    stmt = select(Task).options(selectinload(Task.subcategory).selectinload(Subcategory.group))
    if subcategory_id is not None:
        stmt = stmt.where(Task.subcategory_id == subcategory_id)
    if group_id is not None:
        stmt = stmt.join(Task.subcategory).where(Subcategory.group_id == group_id)
    return list(session.scalars(stmt.order_by(func.lower(Task.name))))


def get_task(session: Session, task_id: int) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise NotFoundError(f"Tarefa {task_id} não encontrada.")
    return task


def _ensure_task_name_free(
    session: Session, subcategory_id: int, name: str, exclude_id: int | None = None
) -> None:
    stmt = select(Task.id).where(
        Task.subcategory_id == subcategory_id, func.lower(Task.name) == name.lower()
    )
    if exclude_id is not None:
        stmt = stmt.where(Task.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ConflictError(f"Já existe uma tarefa '{name}' nesta subcategoria.")


def _default_mode(crons: list[str]) -> ScheduleMode:
    """Without an explicit mode (API clients from before schedule modes existed),
    a schedule means "own" and an empty one means "manual", as it always did."""
    return ScheduleMode.OWN if crons else ScheduleMode.MANUAL


def create_task(session: Session, data: TaskCreate) -> Task:
    get_subcategory(session, data.subcategory_id)
    _ensure_task_name_free(session, data.subcategory_id, data.name)
    values = data.model_dump()
    values["schedule_mode"] = values["schedule_mode"] or _default_mode(values["cron_expressions"])
    if values["schedule_mode"] is ScheduleMode.OWN and not values["cron_expressions"]:
        raise InvalidInputError(OWN_SCHEDULE_REQUIRED)
    task = Task(**values)
    session.add(task)
    bump_config_revision(session)
    session.flush()
    session.refresh(task)
    return task


def update_task(session: Session, task_id: int, data: TaskUpdate) -> Task:
    task = get_task(session, task_id)
    changes = data.model_dump(exclude_unset=True)
    if "subcategory_id" in changes and changes["subcategory_id"] is not None:
        get_subcategory(session, changes["subcategory_id"])
    if "name" in changes or "subcategory_id" in changes:
        _ensure_task_name_free(
            session,
            changes.get("subcategory_id") or task.subcategory_id,
            changes.get("name") or task.name,
            exclude_id=task.id,
        )
    if changes.get("schedule_mode") is None:
        changes.pop("schedule_mode", None)
        if changes.get("cron_expressions") is not None:
            changes["schedule_mode"] = _default_mode(changes["cron_expressions"])
    _apply(task, changes, TASK_NULLABLE_FIELDS)
    if task.schedule_mode is ScheduleMode.OWN and not task.cron_expressions:
        raise InvalidInputError(OWN_SCHEDULE_REQUIRED)
    bump_config_revision(session)
    session.flush()
    session.refresh(task)
    return task


def delete_task(session: Session, task_id: int) -> None:
    session.delete(get_task(session, task_id))
    bump_config_revision(session)
    session.flush()


def next_run(schedule: EffectiveSchedule, timezone: str, now: datetime | None = None):
    if not schedule:
        return None
    try:
        runs = next_fire_times(list(schedule.expressions), timezone, 1, now)
    except CronError:
        return None
    return runs[0] if runs else None


def task_next_run(task: Task, default_timezone: str, now: datetime | None = None):
    if not task.is_effectively_active:
        return None
    schedule = task.effective_schedule
    return next_run(schedule, schedule.tz(default_timezone), now)


def _safe_describe(expressions) -> str:
    try:
        return describe(list(expressions))
    except CronError:
        return "Agendamento inválido"


def group_to_out(group: Group) -> GroupOut:
    return GroupOut.model_validate(
        {
            **{c: getattr(group, c) for c in GroupOut.model_fields if hasattr(group, c)},
            "schedule_description": _safe_describe(group.cron_expressions),
        }
    )


def subcategory_to_out(sub: Subcategory) -> SubcategoryOut:
    from rts.services.sequences import running_sequence  # avoids an import cycle

    inherited = sub.inherited_schedule
    session = object_session(sub)
    running = running_sequence(session, sub.id) if session is not None else None
    return SubcategoryOut.model_validate(
        {
            **{c: getattr(sub, c) for c in SubcategoryOut.model_fields if hasattr(sub, c)},
            "schedule_description": _safe_describe(sub.cron_expressions),
            "inherited_schedule": InheritedScheduleOut(
                source=inherited.source,
                cron_expressions=list(inherited.expressions),
                timezone=inherited.timezone,
                description=_safe_describe(inherited.expressions),
            ),
            "running_sequence_id": running.id if running else None,
        }
    )


def task_to_out(task: Task, default_timezone: str) -> TaskOut:
    schedule = task.effective_schedule
    step = total = None
    if task.runs_in_sequence:
        steps = [t.id for t in task.subcategory.sequence_tasks()]
        total = len(steps)
        step = steps.index(task.id) + 1 if task.id in steps else None
    return TaskOut.model_validate(
        {
            **{c: getattr(task, c) for c in TaskOut.model_fields if hasattr(task, c)},
            "group_id": task.subcategory.group_id,
            "schedule_source": schedule.source,
            "effective_cron_expressions": list(schedule.expressions),
            "schedule_description": _safe_describe(schedule.expressions),
            "effective_timezone": schedule.tz(default_timezone),
            "is_effectively_active": task.is_effectively_active,
            "next_run_at": task_next_run(task, default_timezone),
            "sequence_step": step,
            "sequence_total": total,
        }
    )


def set_sequence_order(session: Session, subcategory_id: int, task_ids: list[int]) -> list[int]:
    """Number the given tasks 1..n; the subcategory's other tasks go after them."""
    sub = get_subcategory(session, subcategory_id)
    tasks = {t.id: t for t in sub.tasks}
    unknown = [i for i in task_ids if i not in tasks]
    if unknown:
        raise InvalidInputError(f"Tarefas que não pertencem a esta subcategoria: {unknown}")
    if len(set(task_ids)) != len(task_ids):
        raise InvalidInputError("Uma tarefa aparece mais de uma vez na ordem.")
    for task in tasks.values():
        task.sequence_position = None
    for position, task_id in enumerate(task_ids, start=1):
        tasks[task_id].sequence_position = position
    session.flush()
    return [t.id for t in sub.sequence_tasks()]

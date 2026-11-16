"""CRUD for groups, subcategories and tasks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from rts.models import Group, Subcategory, Task
from rts.scheduling.cron import CronError, next_fire_times
from rts.schemas.hierarchy import (
    GroupCreate,
    GroupUpdate,
    SubcategoryCreate,
    SubcategoryUpdate,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)
from rts.services.errors import ConflictError, InvalidInputError, NotFoundError
from rts.services.settings import bump_config_revision

TASK_NULLABLE_FIELDS = {"shell", "working_dir", "timezone", "timeout_seconds"}


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
    _apply(group, changes)
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
    _apply(sub, changes)
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


def create_task(session: Session, data: TaskCreate) -> Task:
    get_subcategory(session, data.subcategory_id)
    _ensure_task_name_free(session, data.subcategory_id, data.name)
    task = Task(**data.model_dump())
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
    _apply(task, changes, TASK_NULLABLE_FIELDS)
    bump_config_revision(session)
    session.flush()
    session.refresh(task)
    return task


def delete_task(session: Session, task_id: int) -> None:
    session.delete(get_task(session, task_id))
    bump_config_revision(session)
    session.flush()


def task_next_run(task: Task, timezone: str, now: datetime | None = None) -> datetime | None:
    if not task.cron_expressions or not task.is_effectively_active:
        return None
    try:
        runs = next_fire_times(task.cron_expressions, timezone, 1, now)
    except CronError:
        return None
    return runs[0] if runs else None


def task_to_out(task: Task, default_timezone: str) -> TaskOut:
    effective_tz = task.timezone or default_timezone
    return TaskOut.model_validate(
        {
            **{c: getattr(task, c) for c in TaskOut.model_fields if hasattr(task, c)},
            "group_id": task.subcategory.group_id,
            "effective_timezone": effective_tz,
            "is_effectively_active": task.is_effectively_active,
            "next_run_at": task_next_run(task, effective_tz),
        }
    )

"""Default task workspaces (``<data_dir>/workspaces/<task_id>``).

SQLite reuses the ids of deleted rows, so a workspace left behind by a deleted
task would be inherited by the next task created. Deleting a task (directly or
through its group/subcategory) therefore removes its default workspace. Custom
working directories set by the user are never touched.
"""

from __future__ import annotations

import logging
import shutil

from sqlalchemy import select
from sqlalchemy.orm import Session

from rts.config import Settings
from rts.models import Subcategory, Task

log = logging.getLogger(__name__)


def task_ids_under(
    session: Session, *, group_id: int | None = None, subcategory_id: int | None = None
) -> list[int]:
    stmt = select(Task.id)
    if subcategory_id is not None:
        stmt = stmt.where(Task.subcategory_id == subcategory_id)
    if group_id is not None:
        stmt = stmt.join(Task.subcategory).where(Subcategory.group_id == group_id)
    return list(session.scalars(stmt))


def remove_workspaces(settings: Settings, task_ids: list[int]) -> None:
    base = settings.workspaces_dir.resolve()
    for task_id in task_ids:
        path = (base / str(task_id)).resolve()
        if path.parent != base or not path.exists():
            continue
        shutil.rmtree(path, ignore_errors=True)
        log.info("Diretório de trabalho da tarefa %s removido.", task_id)

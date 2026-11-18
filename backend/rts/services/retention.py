"""Log retention: delete old runs (and their logs) by age and/or count per task."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from rts.models import Run, Task
from rts.models.enums import FINAL_RUN_STATUSES
from rts.services.settings import get_setting

log = logging.getLogger(__name__)

RETENTION_DAYS = "retention_days"
RETENTION_KEEP_LAST = "retention_keep_last"
_BATCH = 500


def get_retention(session: Session) -> tuple[int | None, int | None]:
    return get_setting(session, RETENTION_DAYS), get_setting(session, RETENTION_KEEP_LAST)


def _delete_ids(session: Session, ids: list[int]) -> int:
    for i in range(0, len(ids), _BATCH):
        # Log chunks go with the run (ON DELETE CASCADE).
        session.execute(delete(Run).where(Run.id.in_(ids[i : i + _BATCH])))
    return len(ids)


def apply_retention(
    session: Session,
    now: datetime,
    days: int | None = None,
    keep_last: int | None = None,
    *,
    use_settings: bool = True,
) -> int:
    """Delete finished runs older than ``days`` and beyond the ``keep_last`` newest per task.

    Pending/running runs are never touched. Returns how many runs were deleted.
    """
    if use_settings:
        stored_days, stored_keep = get_retention(session)
        days = days if days is not None else stored_days
        keep_last = keep_last if keep_last is not None else stored_keep
    final = [s.value for s in FINAL_RUN_STATUSES]
    deleted = 0

    if days:
        cutoff = now - timedelta(days=days)
        ids = list(
            session.scalars(select(Run.id).where(Run.created_at < cutoff, Run.status.in_(final)))
        )
        deleted += _delete_ids(session, ids)

    if keep_last:
        for task_id in session.scalars(select(Task.id)):
            ids = list(
                session.scalars(
                    select(Run.id)
                    .where(Run.task_id == task_id, Run.status.in_(final))
                    .order_by(Run.id.desc())
                    .offset(keep_last)
                )
            )
            deleted += _delete_ids(session, ids)

    session.commit()
    if deleted:
        log.info("Retenção de logs: %d execução(ões) antiga(s) removida(s).", deleted)
    return deleted

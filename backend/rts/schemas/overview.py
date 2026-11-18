from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from rts.models import RunStatus
from rts.schemas.runs import RunOut, WorkerStatusOut


class TreeTask(BaseModel):
    id: int
    name: str
    is_active: bool
    is_effectively_active: bool
    running: bool
    last_run_status: RunStatus | None
    last_run_at: datetime | None


class TreeSubcategory(BaseModel):
    id: int
    name: str
    is_active: bool
    is_effectively_active: bool
    has_failure: bool
    tasks: list[TreeTask]


class TreeGroup(BaseModel):
    id: int
    name: str
    is_active: bool
    has_failure: bool
    subcategories: list[TreeSubcategory]


class UpcomingRun(BaseModel):
    task_id: int
    task_name: str
    subcategory_name: str
    group_name: str
    at: datetime


class PeriodStats(BaseModel):
    success: int
    failed: int
    timeout: int
    total: int
    success_rate: float | None


class DashboardStats(BaseModel):
    last_24h: PeriodStats
    last_7d: PeriodStats


class DashboardCounts(BaseModel):
    groups: int
    subcategories: int
    tasks: int
    tasks_active: int
    tasks_paused: int


class DashboardOut(BaseModel):
    running: list[RunOut]
    upcoming: list[UpcomingRun]
    recent_failures: list[RunOut]
    stats: DashboardStats
    counts: DashboardCounts
    worker: WorkerStatusOut

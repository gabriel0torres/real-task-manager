from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from rts.models import LogStream, RunStatus, RunTrigger


class RunOut(BaseModel):
    id: int
    task_id: int
    task_name: str
    status: RunStatus
    trigger: RunTrigger
    attempt: int
    root_run_id: int | None
    scheduled_for: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    exit_code: int | None
    status_reason: str | None
    cancel_requested: bool
    triggered_by: str | None


class RunPage(BaseModel):
    items: list[RunOut]
    total: int


class LogChunkOut(BaseModel):
    seq: int
    ts: datetime
    stream: LogStream
    content: str


class RunLogOut(BaseModel):
    run_id: int
    status: RunStatus
    chunks: list[LogChunkOut]


class WorkerStatusOut(BaseModel):
    online: bool
    worker_id: str | None
    last_seen: datetime | None
    version: str | None

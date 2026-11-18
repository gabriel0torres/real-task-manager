from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from rts.models import LogStream, RunStatus, RunTrigger, SequenceStatus


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
    sequence_run_id: int | None = None
    sequence_index: int | None = None
    sequence_total: int | None = None


class SequenceStepOut(BaseModel):
    index: int
    task_id: int
    task_name: str
    run_id: int | None
    status: str = Field(description="Status da última tentativa, ou not_run.")
    attempt: int | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


class SequenceRunOut(BaseModel):
    id: int
    subcategory_id: int
    status: SequenceStatus
    trigger: RunTrigger
    triggered_by: str | None
    stop_on_failure: bool
    scheduled_for: datetime | None
    created_at: datetime
    finished_at: datetime | None
    status_reason: str | None
    current_index: int
    total_steps: int
    completed_steps: int
    steps: list[SequenceStepOut]


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

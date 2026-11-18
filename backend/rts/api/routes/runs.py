"""Executions: run now, cancel, history, logs (JSON, text and live SSE)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select

from rts.api.deps import SessionDep
from rts.models import Run, RunStatus, WorkerHeartbeat
from rts.models.base import utcnow
from rts.models.enums import FINAL_RUN_STATUSES
from rts.schemas.common import ErrorOut
from rts.schemas.runs import LogChunkOut, RunLogOut, RunOut, RunPage, WorkerStatusOut
from rts.services import runs as svc

router = APIRouter(tags=["Execuções"], responses={404: {"model": ErrorOut}})

WORKER_OFFLINE_AFTER = timedelta(seconds=20)
SSE_POLL_SECONDS = 0.5
SSE_KEEPALIVE_SECONDS = 15.0


def run_to_out(run: Run) -> RunOut:
    return RunOut(
        id=run.id,
        task_id=run.task_id,
        task_name=run.task.name,
        status=run.status,
        trigger=run.trigger,
        attempt=run.attempt,
        root_run_id=run.root_run_id,
        scheduled_for=run.scheduled_for,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=run.duration_ms,
        exit_code=run.exit_code,
        status_reason=run.status_reason,
        cancel_requested=run.cancel_requested,
        triggered_by=run.triggered_by,
        sequence_run_id=run.sequence_run_id,
        sequence_index=run.sequence_index,
        sequence_total=len(run.sequence_run.task_ids) if run.sequence_run else None,
    )


def _wake_embedded_engine(request: Request) -> None:
    engine = getattr(request.app.state, "scheduler_engine", None)
    if engine is not None:
        engine.wake()


@router.post(
    "/tasks/{task_id}/run",
    response_model=RunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Executar agora",
    description=(
        "Cria uma execução com gatilho `manual`. Ela é iniciada pelo motor de agendamento "
        "respeitando a política de sobreposição. Funciona mesmo com a tarefa pausada."
    ),
)
def run_now(task_id: int, session: SessionDep, request: Request):
    run = svc.request_manual_run(session, task_id)
    session.commit()
    _wake_embedded_engine(request)
    return run_to_out(run)


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunOut,
    summary="Cancelar execução",
    description="Pendente: cancela na hora. Em andamento: encerra o processo e seus filhos.",
    responses={409: {"model": ErrorOut}},
)
def cancel(run_id: int, session: SessionDep, request: Request):
    run = svc.cancel_run(session, run_id)
    session.commit()
    _wake_embedded_engine(request)
    return run_to_out(run)


@router.get("/runs", response_model=RunPage, summary="Histórico de execuções")
def list_runs(
    session: SessionDep,
    task_id: int | None = None,
    status_: Annotated[list[RunStatus] | None, Query(alias="status")] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = svc.list_runs(
        session,
        task_id=task_id,
        statuses=status_,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return RunPage(items=[run_to_out(r) for r in items], total=total)


@router.get("/runs/{run_id}", response_model=RunOut, summary="Obter execução")
def get_run(run_id: int, session: SessionDep):
    return run_to_out(svc.get_run(session, run_id))


@router.get("/runs/{run_id}/log", response_model=RunLogOut, summary="Log da execução (JSON)")
def get_log(run_id: int, session: SessionDep, after_seq: Annotated[int, Query(ge=0)] = 0):
    run = svc.get_run(session, run_id)
    chunks = svc.get_log_chunks(session, run_id, after_seq)
    return RunLogOut(
        run_id=run.id,
        status=run.status,
        chunks=[LogChunkOut.model_validate(c, from_attributes=True) for c in chunks],
    )


@router.get(
    "/runs/{run_id}/log.txt",
    response_class=PlainTextResponse,
    summary="Log da execução (texto puro, para download)",
)
def get_log_text(run_id: int, session: SessionDep):
    svc.get_run(session, run_id)
    return "".join(c.content for c in svc.get_log_chunks(session, run_id))


@router.get(
    "/runs/{run_id}/log/stream",
    summary="Log em tempo real (Server-Sent Events)",
    description=(
        "Eventos: `log` (id = seq do trecho), `status` (mudança de status) e `end`. "
        "Reconexões podem enviar `Last-Event-ID` para continuar de onde pararam."
    ),
    response_class=StreamingResponse,
)
async def stream_log(
    run_id: int,
    request: Request,
    session: SessionDep,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
):
    svc.get_run(session, run_id)  # 404 before opening the stream
    session.close()
    factory = request.app.state.session_factory
    start_seq = int(last_event_id) if last_event_id and last_event_id.isdigit() else after_seq

    def fetch(seq: int):
        with factory() as s:
            # Status first: once final, every chunk has already been committed.
            run_status = s.scalar(select(Run.status).where(Run.id == run_id))
            chunks = [
                (c.seq, c.ts.isoformat(), c.stream.value, c.content)
                for c in svc.get_log_chunks(s, run_id, seq)
            ]
        return run_status, chunks

    async def events():
        seq = start_seq
        last_status = None
        idle = 0.0
        while True:
            if await request.is_disconnected():
                return
            run_status, chunks = await run_in_threadpool(fetch, seq)
            if run_status is None:  # run deleted meanwhile
                yield "event: end\ndata: {}\n\n"
                return
            for c_seq, ts, stream, content in chunks:
                data = json.dumps({"seq": c_seq, "ts": ts, "stream": stream, "content": content})
                yield f"id: {c_seq}\nevent: log\ndata: {data}\n\n"
                seq = c_seq
            if run_status != last_status:
                last_status = run_status
                yield f"event: status\ndata: {json.dumps({'status': run_status.value})}\n\n"
            if run_status in FINAL_RUN_STATUSES and not chunks:
                yield "event: end\ndata: {}\n\n"
                return
            if chunks:
                idle = 0.0
            else:
                idle += SSE_POLL_SECONDS
                if idle >= SSE_KEEPALIVE_SECONDS:
                    idle = 0.0
                    yield ": keepalive\n\n"
            await asyncio.sleep(SSE_POLL_SECONDS)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/system/worker",
    response_model=WorkerStatusOut,
    tags=["Sistema"],
    summary="Estado do motor de agendamento",
)
def worker_status(session: SessionDep):
    row = session.scalars(
        select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen.desc()).limit(1)
    ).first()
    if row is None:
        return WorkerStatusOut(online=False, worker_id=None, last_seen=None, version=None)
    return WorkerStatusOut(
        online=utcnow() - row.last_seen < WORKER_OFFLINE_AFTER,
        worker_id=row.worker_id,
        last_seen=row.last_seen,
        version=row.version,
    )

"""The scheduling engine (runs in the worker process, or embedded in the API).

Design
------
* The database is the only source of truth and the only channel between the API
  and the engine: the API creates ``pending`` runs ("run now"), sets
  ``cancel_requested`` and bumps ``config_revision``; the engine polls for them.
* APScheduler computes *when* tasks fire. A custom executor receives the exact
  scheduled time of each fire and turns it into a ``pending`` run.
* ``dispatch()`` applies the overlap policy and starts runs in executor threads.
* On start, runs left ``running`` by a crash are failed ("interrompida por
  reinício") and the missed-run policy is applied for the downtime window.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta

import psutil
from apscheduler.executors.base import BaseExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from rts import __version__
from rts.engine.context import EngineContext
from rts.engine.executor import RunExecutor
from rts.engine.process import kill_tree
from rts.models import (
    MisfirePolicy,
    OverlapPolicy,
    Run,
    RunStatus,
    RunTrigger,
    Subcategory,
    Task,
    WorkerHeartbeat,
)
from rts.scheduling.cron import CronError, build_trigger, fire_times_between
from rts.services.retention import apply_retention
from rts.services.runs import append_system_log, create_run, finish_without_running
from rts.services.settings import CONFIG_REVISION, get_default_timezone, get_setting

log = logging.getLogger(__name__)

INTERRUPTED_REASON = "Interrompida por reinício."
SKIPPED_BUSY_REASON = "Pulada: a execução anterior ainda está em andamento."
SKIPPED_QUEUE_FULL_REASON = "Pulada: já existe uma execução aguardando na fila."
HEARTBEAT_RETENTION = timedelta(days=7)
RETENTION_INTERVAL_SECONDS = 3600


class _FireExecutor(BaseExecutor):
    """APScheduler executor that forwards (task_id, scheduled_time) synchronously."""

    def __init__(self, on_fire) -> None:
        super().__init__()
        self._on_fire = on_fire

    def _do_submit_job(self, job, run_times):
        # BaseExecutor.submit_job increments the instance counter *after* this
        # returns, so the success call below nets the counter back to zero.
        try:
            for run_time in run_times:
                self._on_fire(job.args[0], run_time)
        except Exception as exc:  # pragma: no cover - logged by APScheduler
            self._run_job_error(job.id, exc, exc.__traceback__)
        else:
            self._run_job_success(job.id, [])


def _job_id(task_id: int) -> str:
    return f"task-{task_id}"


def _never_called(task_id: int) -> None:  # pragma: no cover
    """Job target placeholder: _FireExecutor handles fires without calling it."""


def _kill_orphan(run: Run) -> None:
    """Kill a process left behind by a crashed worker.

    Task processes run in their own session, so they can outlive the worker. The
    process creation time is compared with the run start to avoid killing an
    unrelated process that reused the PID.
    """
    if not run.pid or run.started_at is None:
        return
    try:
        created = psutil.Process(run.pid).create_time()
    except psutil.Error:
        return
    started = run.started_at.timestamp()
    if started - 10 <= created <= started + 60:
        log.warning("Encerrando processo órfão %s da execução #%s.", run.pid, run.id)
        kill_tree(run.pid)


class SchedulerEngine:
    def __init__(
        self,
        ctx: EngineContext,
        *,
        worker_id: str | None = None,
        poll_interval: float = 1.0,
        heartbeat_interval: float = 5.0,
    ) -> None:
        self.ctx = ctx
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval

        self._scheduler = BackgroundScheduler(
            timezone=UTC,
            executors={"default": _FireExecutor(self.on_fire)},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": None},
        )
        self._job_signatures: dict[int, tuple] = {}
        self._config_revision: int | None = None
        self._executors: dict[int, tuple[RunExecutor, threading.Thread]] = {}
        self._executors_lock = threading.Lock()
        self._dispatch_lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._loop_thread: threading.Thread | None = None
        self._last_heartbeat = 0.0
        self._last_retention = 0.0  # 0 = apply on the first tick
        self.started = False

    # ================================================================ lifecycle
    def start(self) -> None:
        self.recover()
        self._heartbeat(initial=True)
        self.reload_jobs(force=True)
        self._scheduler.start()
        self._loop_thread = threading.Thread(target=self._loop, name="rts-engine", daemon=True)
        self._loop_thread.start()
        self.started = True
        log.info("Motor de agendamento iniciado (worker %s).", self.worker_id)

    def stop(self, timeout: float = 15.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        if self._loop_thread is not None:
            self._loop_thread.join(timeout)
        with self._executors_lock:
            running = list(self._executors.values())
        for executor, _ in running:
            executor.interrupt(INTERRUPTED_REASON)
        for _, thread in running:
            thread.join(timeout)
        if self.started:
            self._heartbeat()
        self.started = False
        log.info("Motor de agendamento parado.")

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # pragma: no cover - keep the engine alive
                log.exception("Erro no ciclo do motor de agendamento")
            self._wake.wait(self.poll_interval)
            self._wake.clear()

    def tick(self) -> None:
        now = self.ctx.clock().timestamp()
        if now - self._last_heartbeat >= self.heartbeat_interval:
            self._heartbeat()
        self.reload_jobs()
        self.dispatch()
        if now - self._last_retention >= RETENTION_INTERVAL_SECONDS:
            self._last_retention = now
            with self.ctx.session_factory() as session:
                apply_retention(session, self.ctx.clock())

    # ================================================================ heartbeat
    def _heartbeat(self, initial: bool = False) -> None:
        now = self.ctx.clock()
        with self.ctx.session_factory() as session:
            row = session.get(WorkerHeartbeat, self.worker_id)
            if row is None:
                session.add(
                    WorkerHeartbeat(
                        worker_id=self.worker_id, started_at=now, last_seen=now, version=__version__
                    )
                )
            else:
                row.last_seen = now
            if initial:
                session.execute(
                    delete(WorkerHeartbeat).where(
                        WorkerHeartbeat.last_seen < now - HEARTBEAT_RETENTION
                    )
                )
            session.commit()
        self._last_heartbeat = now.timestamp()

    # ================================================================ recovery
    def recover(self) -> None:
        """Fail runs interrupted by a crash and apply the missed-run policy."""
        now = self.ctx.clock()
        interrupted: list[int] = []
        with self.ctx.session_factory() as session:
            for run in session.scalars(select(Run).where(Run.status == RunStatus.RUNNING)):
                interrupted.append(run.id)
                _kill_orphan(run)
                run.status = RunStatus.FAILED
                run.status_reason = INTERRUPTED_REASON
                run.finished_at = now
                if run.started_at is not None:
                    run.duration_ms = int((now - run.started_at).total_seconds() * 1000)
                append_system_log(session, run.id, INTERRUPTED_REASON)
                log.warning("Execução #%s marcada como interrompida por reinício.", run.id)

            downtime_start = session.scalar(select(func.max(WorkerHeartbeat.last_seen)))
            if downtime_start is not None:
                self._apply_missed_runs(session, downtime_start, now)
            session.commit()
        if self.ctx.notifier is not None:
            for run_id in interrupted:
                self.ctx.notifier.notify_run(run_id)

    def _apply_missed_runs(self, session: Session, downtime_start: datetime, now: datetime) -> None:
        default_tz = get_default_timezone(session, self.ctx.settings.default_timezone)
        for task in self._load_tasks(session):
            schedule = task.effective_schedule
            if not task.is_effectively_active or not schedule:
                continue
            # Tasks created while the engine was down only miss fires after creation.
            since = max(downtime_start, task.last_fire_at or downtime_start, task.created_at)
            try:
                missed = fire_times_between(
                    list(schedule.expressions), schedule.tz(default_tz), since, now
                )
            except CronError:
                continue
            if not missed:
                continue
            task.last_fire_at = missed[-1]
            if task.misfire_policy is MisfirePolicy.RUN_ONCE:
                run = create_run(session, task.id, RunTrigger.SCHEDULED, scheduled_for=missed[-1])
                append_system_log(
                    session,
                    run.id,
                    f"{len(missed)} execução(ões) perdida(s) enquanto o servidor estava fora do ar"
                    " - executando uma vez (política: executar ao voltar).",
                )
                log.info(
                    "Tarefa %s: %d execução(ões) perdida(s), executando uma vez.",
                    task.id,
                    len(missed),
                )
            else:
                log.info(
                    "Tarefa %s: %d execução(ões) perdida(s) ignorada(s).", task.id, len(missed)
                )

    # ================================================================ jobs
    @staticmethod
    def _load_tasks(session: Session) -> list[Task]:
        stmt = select(Task).options(selectinload(Task.subcategory).selectinload(Subcategory.group))
        return list(session.scalars(stmt))

    def reload_jobs(self, force: bool = False) -> bool:
        """Sync APScheduler jobs with the database when the config revision changes."""
        with self.ctx.session_factory() as session:
            revision = int(get_setting(session, CONFIG_REVISION, 0))
            if not force and revision == self._config_revision:
                return False
            default_tz = get_default_timezone(session, self.ctx.settings.default_timezone)
            desired: dict[int, tuple] = {}
            for task in self._load_tasks(session):
                # The effective schedule may be inherited from the subcategory or group.
                schedule = task.effective_schedule
                if task.is_effectively_active and schedule:
                    desired[task.id] = (schedule.expressions, schedule.tz(default_tz))

        for task_id in set(self._job_signatures) - set(desired):
            if self._scheduler.get_job(_job_id(task_id)):
                self._scheduler.remove_job(_job_id(task_id))
            del self._job_signatures[task_id]

        for task_id, signature in desired.items():
            if self._job_signatures.get(task_id) == signature:
                continue
            crons, tz = signature
            try:
                trigger = build_trigger(list(crons), tz)
            except CronError as exc:
                log.error("Tarefa %s com agendamento inválido: %s", task_id, exc)
                continue
            self._scheduler.add_job(
                _never_called,
                trigger=trigger,
                args=[task_id],
                id=_job_id(task_id),
                replace_existing=True,
            )
            self._job_signatures[task_id] = signature

        self._config_revision = revision
        log.debug("Agendamentos recarregados (revisão %s, %d tarefas).", revision, len(desired))
        return True

    def scheduled_jobs(self) -> dict[int, datetime | None]:
        """task_id -> next fire time (for diagnostics and tests)."""
        return {
            int(job.id.removeprefix("task-")): getattr(job, "next_run_time", None)
            for job in self._scheduler.get_jobs()
        }

    def on_fire(self, task_id: int, scheduled_time: datetime) -> Run | None:
        """A schedule fired: record it and create a pending run (respecting misfires)."""
        now = self.ctx.clock()
        with self.ctx.session_factory() as session:
            task = session.get(Task, task_id)
            if task is None or not task.is_effectively_active or not task.effective_schedule:
                return None
            if task.last_fire_at is not None and scheduled_time <= task.last_fire_at:
                return None  # already handled (e.g. by recovery)
            task.last_fire_at = scheduled_time
            late = (now - scheduled_time).total_seconds()
            if late > self.ctx.settings.misfire_grace_seconds and (
                task.misfire_policy is MisfirePolicy.IGNORE
            ):
                log.warning(
                    "Tarefa %s: disparo de %s atrasado %.0fs, ignorado.",
                    task_id,
                    scheduled_time,
                    late,
                )
                session.commit()
                return None
            run = create_run(session, task.id, RunTrigger.SCHEDULED, scheduled_for=scheduled_time)
            session.commit()
        self.wake()
        return run

    # ================================================================ dispatch
    @staticmethod
    def _is_busy(session: Session, task_id: int, exclude_run_id: int) -> bool:
        """Running, or waiting between retries (decision: counts as busy)."""
        stmt = select(Run.id).where(
            Run.task_id == task_id,
            Run.id != exclude_run_id,
            (Run.status == RunStatus.RUNNING)
            | ((Run.status == RunStatus.PENDING) & (Run.trigger == RunTrigger.RETRY)),
        )
        return session.scalar(stmt.limit(1)) is not None

    @staticmethod
    def _has_earlier_waiting(session: Session, run: Run) -> bool:
        stmt = select(Run.id).where(
            Run.task_id == run.task_id,
            Run.status == RunStatus.PENDING,
            Run.trigger != RunTrigger.RETRY,
            Run.id < run.id,
        )
        return session.scalar(stmt.limit(1)) is not None

    def dispatch(self) -> list[int]:
        """Start every pending run that may start now. Returns the started run ids."""
        started: list[int] = []
        with self._dispatch_lock, self.ctx.session_factory() as session:
            now = self.ctx.clock()
            pending = session.scalars(
                select(Run)
                .options(selectinload(Run.task))
                .where(Run.status == RunStatus.PENDING)
                .order_by(Run.id)
            ).all()
            for run in pending:
                if run.status is not RunStatus.PENDING:
                    continue
                if run.trigger is RunTrigger.RETRY:
                    if run.scheduled_for is not None and run.scheduled_for > now:
                        continue
                else:
                    policy = run.task.overlap_policy
                    if policy is not OverlapPolicy.PARALLEL and self._is_busy(
                        session, run.task_id, run.id
                    ):
                        if policy is OverlapPolicy.SKIP:
                            finish_without_running(
                                session, run, RunStatus.SKIPPED, SKIPPED_BUSY_REASON, now
                            )
                        elif self._has_earlier_waiting(session, run):
                            finish_without_running(
                                session, run, RunStatus.SKIPPED, SKIPPED_QUEUE_FULL_REASON, now
                            )
                        session.flush()
                        continue
                    if policy is OverlapPolicy.QUEUE and self._has_earlier_waiting(session, run):
                        continue  # FIFO: an older queued run goes first

                claimed = session.execute(
                    update(Run)
                    .where(Run.id == run.id, Run.status == RunStatus.PENDING)
                    .values(status=RunStatus.RUNNING, started_at=now)
                    .execution_options(synchronize_session=False)
                ).rowcount
                session.flush()
                session.refresh(run)
                if claimed == 1:
                    started.append(run.id)
            session.commit()

        for run_id in started:
            self._start_executor(run_id)
        return started

    def _start_executor(self, run_id: int) -> None:
        executor = RunExecutor(self.ctx, run_id)

        def target() -> None:
            try:
                executor.execute()
            finally:
                with self._executors_lock:
                    self._executors.pop(run_id, None)
                self.wake()  # a queued run may start now

        thread = threading.Thread(target=target, name=f"rts-run-{run_id}", daemon=True)
        with self._executors_lock:
            self._executors[run_id] = (executor, thread)
        thread.start()

    # ================================================================ helpers
    def running_run_ids(self) -> list[int]:
        with self._executors_lock:
            return list(self._executors)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Wait until no run is executing in this engine (tests/diagnostics)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._executors_lock:
                threads = [t for _, t in self._executors.values()]
            if not threads:
                return True
            for thread in threads:
                thread.join(0.1)
        return False

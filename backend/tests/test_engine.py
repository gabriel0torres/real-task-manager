"""Execution engine tests (real subprocesses, shell = python for portability)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import psutil
import pytest
from sqlalchemy import select

from rts.engine.context import EngineContext
from rts.engine.scheduler import INTERRUPTED_REASON, SchedulerEngine
from rts.models import Run, RunLogChunk, RunStatus, RunTrigger, Task, WorkerHeartbeat
from rts.services.runs import create_run
from tests.conftest import API


# --------------------------------------------------------------------------- fixtures/helpers
@pytest.fixture
def engine(app):
    eng = SchedulerEngine(
        EngineContext(app.state.settings, app.state.session_factory, app.state.secret_box),
        poll_interval=0.1,
    )
    yield eng
    eng.stop(timeout=20)


@pytest.fixture
def py_task(make):
    """Create a task executed with the python 'shell'."""

    def _make(command: str, **kw):
        g = make.group(kw.pop("group_name", "g"))
        s = make.subcategory(g["id"], "s")
        kw.setdefault("cron_expressions", [])
        return make.task(s["id"], kw.pop("name", "t"), command=command, shell="python", **kw)

    return _make


def run_now(client, task_id: int) -> int:
    resp = client.post(f"{API}/tasks/{task_id}/run")
    assert resp.status_code == 202, resp.text
    return resp.json()["id"]


def get_run(db, run_id: int) -> Run:
    db.expire_all()
    return db.get(Run, run_id)


def log_text(db, run_id: int, stream: str | None = None) -> str:
    db.expire_all()
    stmt = select(RunLogChunk).where(RunLogChunk.run_id == run_id).order_by(RunLogChunk.seq)
    return "".join(c.content for c in db.scalars(stmt) if stream is None or c.stream == stream)


def wait_for(predicate, timeout: float = 15.0, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    raise AssertionError("condition not met in time")


def execute(engine, client, task_id: int) -> int:
    run_id = run_now(client, task_id)
    assert run_id in engine.dispatch()
    assert engine.wait_idle(30)
    return run_id


# --------------------------------------------------------------------------- executor
def test_successful_run_captures_stdout_and_stderr(engine, client, db, py_task):
    t = py_task("import sys\nprint('olá mundo')\nprint('aviso', file=sys.stderr)")
    run_id = execute(engine, client, t["id"])
    run = get_run(db, run_id)
    assert run.status is RunStatus.SUCCESS and run.exit_code == 0
    assert run.trigger is RunTrigger.MANUAL and run.attempt == 1
    assert run.started_at and run.finished_at and run.duration_ms is not None and run.pid
    assert "olá mundo" in log_text(db, run_id, "stdout")
    assert "aviso" in log_text(db, run_id, "stderr")
    system = log_text(db, run_id, "system")
    assert "gatilho: manual" in system and "Finalizada: sucesso" in system


def test_default_system_shell_multiline_script(engine, client, db, make):
    """No shell set: cmd on Windows, bash/sh elsewhere. Exit code of the script is kept."""
    g = make.group()
    s = make.subcategory(g["id"])
    t = make.task(s["id"], command="echo primeira\necho segunda\nexit 4", cron_expressions=[])
    run = get_run(db, execute(engine, client, t["id"]))
    out = log_text(db, run.id, "stdout")
    assert "primeira" in out and "segunda" in out
    assert run.status is RunStatus.FAILED and run.exit_code == 4


def test_failure_exit_code(engine, client, db, py_task):
    t = py_task("import sys\nsys.exit(3)")
    run = get_run(db, execute(engine, client, t["id"]))
    assert run.status is RunStatus.FAILED and run.exit_code == 3
    assert run.status_reason == "Código de saída 3."


def test_environment_inheritance_metadata_and_masking(
    engine, client, db, make, py_task, monkeypatch
):
    monkeypatch.setenv("RTS_SECRET_KEY", "must-not-leak")
    t = py_task(
        "import os\n"
        "keys = ['ENV_NAME', 'API_TOKEN', 'RTS_TASK', 'RTS_GROUP', 'RTS_TRIGGER', 'RTS_ATTEMPT']\n"
        "for k in keys:\n"
        "    print(k, '=', os.environ.get(k))\n"
        "print('KEY_LEAK', os.environ.get('RTS_SECRET_KEY'))\n"
        "print('token again: ' + os.environ['API_TOKEN'])\n"
    )
    make.variable("global", "ENV_NAME", "global")
    make.variable("task", "ENV_NAME", "from-task", owner_id=t["id"])
    make.variable("global", "API_TOKEN", "tok-123-secret", is_secret=True)

    run_id = execute(engine, client, t["id"])
    out = log_text(db, run_id)
    assert "ENV_NAME = from-task" in out
    assert "RTS_TASK = t" in out and "RTS_GROUP = g" in out
    assert "RTS_TRIGGER = manual" in out and "RTS_ATTEMPT = 1" in out
    assert "KEY_LEAK None" in out
    assert "tok-123-secret" not in out
    assert "API_TOKEN = ****" in out and "token again: ****" in out


def test_timeout_kills_process(engine, client, db, py_task):
    t = py_task("import time\nprint('start', flush=True)\ntime.sleep(60)", timeout_seconds=1)
    started = time.monotonic()
    run = get_run(db, execute(engine, client, t["id"]))
    assert time.monotonic() - started < 15
    assert run.status is RunStatus.TIMEOUT
    assert run.status_reason == "Tempo limite de 1s excedido."
    assert "start" in log_text(db, run.id)


def test_cancel_running_kills_process_tree(engine, client, db, py_task, settings):
    t = py_task(
        "import subprocess, sys, time, pathlib\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "pathlib.Path('child.pid').write_text(str(child.pid))\n"
        "print('running', flush=True)\n"
        "time.sleep(60)\n"
    )
    pid_file = settings.workspaces_dir / str(t["id"]) / "child.pid"
    run_id = run_now(client, t["id"])
    engine.dispatch()
    wait_for(lambda: pid_file.exists() and pid_file.read_text())
    child_pid = int(pid_file.read_text())
    assert psutil.pid_exists(child_pid)

    resp = client.post(f"{API}/runs/{run_id}/cancel")
    assert resp.status_code == 200 and resp.json()["cancel_requested"] is True
    assert engine.wait_idle(30)

    run = get_run(db, run_id)
    assert run.status is RunStatus.CANCELLED
    assert run.status_reason == "Cancelada pelo usuário."
    wait_for(
        lambda: (
            not psutil.pid_exists(child_pid)
            or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
        ),
        timeout=10,
    )


def test_retries_until_max_attempts(engine, client, db, py_task):
    t = py_task("import sys\nsys.exit(1)", max_retries=2, retry_interval_seconds=0)
    first = execute(engine, client, t["id"])
    for _ in range(2):
        engine.dispatch()
        assert engine.wait_idle(30)
    assert engine.dispatch() == []  # no 4th attempt

    db.expire_all()
    runs = db.scalars(select(Run).where(Run.task_id == t["id"]).order_by(Run.id)).all()
    assert [(r.attempt, r.trigger, r.status) for r in runs] == [
        (1, RunTrigger.MANUAL, RunStatus.FAILED),
        (2, RunTrigger.RETRY, RunStatus.FAILED),
        (3, RunTrigger.RETRY, RunStatus.FAILED),
    ]
    assert runs[1].root_run_id == first and runs[2].root_run_id == first
    assert "Nova tentativa 2/3" in log_text(db, first)


def test_retry_waits_for_interval_and_success_does_not_retry(engine, client, db, py_task):
    t = py_task("import sys\nsys.exit(1)", max_retries=1, retry_interval_seconds=3600)
    execute(engine, client, t["id"])
    assert engine.dispatch() == []  # retry not due yet
    db.expire_all()
    retry = db.scalars(select(Run).where(Run.trigger == RunTrigger.RETRY)).one()
    assert retry.status is RunStatus.PENDING and retry.scheduled_for > datetime.now(UTC)

    ok = py_task("print('ok')", max_retries=3, group_name="g2")
    execute(engine, client, ok["id"])
    db.expire_all()
    assert (
        db.scalars(select(Run).where(Run.task_id == ok["id"])).all()[0].status is RunStatus.SUCCESS
    )
    assert len(db.scalars(select(Run).where(Run.task_id == ok["id"])).all()) == 1


def test_missing_variable_value_fails_without_retry(engine, client, db, py_task):
    from rts.models import Variable

    t = py_task("print('never')", max_retries=3)
    db.add(
        Variable(scope="task", task_id=t["id"], key="PENDING_SECRET", value=None, is_secret=True)
    )
    db.commit()
    run = get_run(db, execute(engine, client, t["id"]))
    assert run.status is RunStatus.FAILED
    assert "PENDING_SECRET" in run.status_reason
    assert engine.dispatch() == []  # configuration errors are not retried


def test_missing_working_dir_fails(engine, client, db, py_task, tmp_path):
    t = py_task("print('x')", working_dir=str(tmp_path / "nope"))
    run = get_run(db, execute(engine, client, t["id"]))
    assert run.status is RunStatus.FAILED
    assert "Diretório de trabalho não encontrado" in run.status_reason


def test_custom_working_dir(engine, client, db, py_task, tmp_path):
    t = py_task("import os\nprint('cwd=' + os.getcwd())", working_dir=str(tmp_path))
    run_id = execute(engine, client, t["id"])
    assert f"cwd={tmp_path}" in log_text(db, run_id)


def test_log_is_truncated_at_limit(app, client, db, py_task):
    app.state.settings.max_log_bytes = 1000
    eng = SchedulerEngine(
        EngineContext(app.state.settings, app.state.session_factory, app.state.secret_box)
    )
    try:
        t = py_task("for i in range(2000):\n    print('linha', i)")
        run_id = execute(eng, client, t["id"])
    finally:
        eng.stop()
    assert get_run(db, run_id).status is RunStatus.SUCCESS
    assert len(log_text(db, run_id, "stdout")) <= 1000
    assert "Log truncado" in log_text(db, run_id, "system")


# --------------------------------------------------------------------------- overlap policies
def _start_sleeper(engine, client, task_id) -> int:
    run_id = run_now(client, task_id)
    assert engine.dispatch() == [run_id]
    return run_id


def _cancel_and_wait(engine, client, run_id):
    client.post(f"{API}/runs/{run_id}/cancel")
    assert engine.wait_idle(30)


def test_overlap_skip(engine, client, db, py_task):
    t = py_task("import time\ntime.sleep(60)", overlap_policy="skip")
    first = _start_sleeper(engine, client, t["id"])
    second = run_now(client, t["id"])
    assert engine.dispatch() == []
    run = get_run(db, second)
    assert run.status is RunStatus.SKIPPED and "em andamento" in run.status_reason
    _cancel_and_wait(engine, client, first)


def test_overlap_queue_keeps_one_waiting(engine, client, db, py_task):
    t = py_task("import time\ntime.sleep(60)", overlap_policy="queue")
    first = _start_sleeper(engine, client, t["id"])
    queued = run_now(client, t["id"])
    extra = run_now(client, t["id"])
    assert engine.dispatch() == []
    assert get_run(db, queued).status is RunStatus.PENDING
    assert get_run(db, extra).status is RunStatus.SKIPPED
    assert "fila" in get_run(db, extra).status_reason

    _cancel_and_wait(engine, client, first)
    assert engine.dispatch() == [queued]
    _cancel_and_wait(engine, client, queued)


def test_overlap_parallel(engine, client, db, py_task):
    t = py_task("import time\ntime.sleep(60)", overlap_policy="parallel")
    a = _start_sleeper(engine, client, t["id"])
    b = run_now(client, t["id"])
    assert engine.dispatch() == [b]
    client.post(f"{API}/runs/{a}/cancel")
    _cancel_and_wait(engine, client, b)
    assert get_run(db, a).status is RunStatus.CANCELLED


def test_waiting_retry_counts_as_busy(engine, client, db, py_task):
    t = py_task("import sys\nsys.exit(1)", max_retries=1, retry_interval_seconds=3600)
    execute(engine, client, t["id"])  # failed, retry pending in 1h
    manual = run_now(client, t["id"])
    engine.dispatch()
    assert get_run(db, manual).status is RunStatus.SKIPPED


def test_stop_interrupts_running_runs(engine, client, db, py_task):
    t = py_task("import time\ntime.sleep(60)")
    run_id = _start_sleeper(engine, client, t["id"])
    wait_for(lambda: get_run(db, run_id).pid is not None)
    engine.stop()
    run = get_run(db, run_id)
    assert run.status is RunStatus.FAILED and run.status_reason == INTERRUPTED_REASON


# --------------------------------------------------------------------------- scheduling
def _task_row(db, task_id) -> Task:
    db.expire_all()
    return db.get(Task, task_id)


def test_on_fire_creates_scheduled_run_once(engine, db, py_task):
    t = py_task("print(1)", cron_expressions=["0 8 * * *"])
    fire = datetime.now(UTC).replace(second=0, microsecond=0)
    run = engine.on_fire(t["id"], fire)
    assert run is not None and run.trigger is RunTrigger.SCHEDULED
    assert get_run(db, run.id).scheduled_for == fire
    assert _task_row(db, t["id"]).last_fire_at == fire
    assert engine.on_fire(t["id"], fire) is None  # duplicate fire ignored


def test_on_fire_ignores_paused_and_late_fires(engine, client, db, py_task):
    t = py_task("print(1)", cron_expressions=["0 8 * * *"])
    late = datetime.now(UTC) - timedelta(minutes=10)
    assert engine.on_fire(t["id"], late) is None  # misfire_policy=ignore
    assert _task_row(db, t["id"]).last_fire_at == late

    client.patch(f"{API}/tasks/{t['id']}", json={"misfire_policy": "run_once"})
    assert engine.on_fire(t["id"], late + timedelta(minutes=1)) is not None

    client.patch(f"{API}/groups/{t['group_id']}", json={"is_active": False})
    assert engine.on_fire(t["id"], datetime.now(UTC)) is None


def test_reload_jobs_follows_config_changes(engine, client, py_task):
    t = py_task("print(1)", cron_expressions=["30 8 * * *"], timezone="UTC")
    other = py_task("print(1)", cron_expressions=[], group_name="g2", name="manual")
    assert engine.reload_jobs(force=True)
    jobs = engine.scheduled_jobs()
    assert set(jobs) == {t["id"]} and other["id"] not in jobs

    assert engine.reload_jobs() is False  # no change -> no reload

    client.patch(f"{API}/subcategories/{t['subcategory_id']}", json={"is_active": False})
    assert engine.reload_jobs() is True
    assert engine.scheduled_jobs() == {}

    client.patch(f"{API}/subcategories/{t['subcategory_id']}", json={"is_active": True})
    client.patch(f"{API}/tasks/{t['id']}", json={"cron_expressions": ["0 9 * * *", "0 21 * * *"]})
    engine.reload_jobs()
    assert set(engine.scheduled_jobs()) == {t["id"]}


def test_apscheduler_fires_through_engine(app, client, db, py_task, monkeypatch):
    """End-to-end: the real BackgroundScheduler fires -> run created -> executed."""
    from apscheduler.triggers.interval import IntervalTrigger

    import rts.engine.scheduler as sched_mod

    monkeypatch.setattr(sched_mod, "build_trigger", lambda *_a, **_k: IntervalTrigger(seconds=1))
    t = py_task("print('scheduled hello')", cron_expressions=["* * * * *"])
    eng = SchedulerEngine(
        EngineContext(app.state.settings, app.state.session_factory, app.state.secret_box),
        poll_interval=0.1,
    )
    eng.start()
    try:

        def done():
            db.expire_all()
            return db.scalars(
                select(Run).where(Run.task_id == t["id"], Run.status == RunStatus.SUCCESS)
            ).first()

        wait_for(done, timeout=20)
        run = done()
        assert run.trigger is RunTrigger.SCHEDULED and run.scheduled_for is not None
        assert "scheduled hello" in log_text(db, run.id)
        assert db.get(WorkerHeartbeat, eng.worker_id) is not None
    finally:
        eng.stop()


# --------------------------------------------------------------------------- recovery
def _clocked_engine(app, now: datetime) -> SchedulerEngine:
    ctx = EngineContext(
        app.state.settings, app.state.session_factory, app.state.secret_box, clock=lambda: now
    )
    return SchedulerEngine(ctx)


def test_recover_marks_running_runs_as_interrupted(app, db, py_task):
    t = py_task("print(1)")
    run = create_run(db, t["id"], RunTrigger.MANUAL)
    run.status = RunStatus.RUNNING
    run.started_at = datetime.now(UTC) - timedelta(minutes=5)
    run.pid = 999_999_999  # not a live process
    db.commit()

    _clocked_engine(app, datetime.now(UTC)).recover()
    run = get_run(db, run.id)
    assert run.status is RunStatus.FAILED and run.status_reason == INTERRUPTED_REASON
    assert run.finished_at is not None and run.duration_ms >= 5 * 60 * 1000
    assert INTERRUPTED_REASON in log_text(db, run.id)


def _setup_downtime(db, task_id, now, policy):
    task = db.get(Task, task_id)
    task.created_at = now - timedelta(days=1)
    task.misfire_policy = policy
    task.timezone = "UTC"
    db.add(
        WorkerHeartbeat(
            worker_id="old",
            started_at=now - timedelta(days=1),
            last_seen=now - timedelta(hours=2, minutes=5),
            version="0",
        )
    )
    db.commit()


def test_missed_runs_run_once_after_downtime(app, db, py_task):
    now = datetime(2026, 11, 16, 12, 10, tzinfo=UTC)
    t = py_task("print(1)", cron_expressions=["*/30 * * * *"])
    _setup_downtime(db, t["id"], now, "run_once")

    _clocked_engine(app, now).recover()
    db.expire_all()
    runs = db.scalars(select(Run).where(Run.task_id == t["id"])).all()
    assert len(runs) == 1  # 10:30, 11:00, 11:30, 12:00 missed -> executed once
    assert runs[0].status is RunStatus.PENDING and runs[0].trigger is RunTrigger.SCHEDULED
    assert runs[0].scheduled_for == datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    assert "4 execução(ões) perdida(s)" in log_text(db, runs[0].id)
    assert _task_row(db, t["id"]).last_fire_at == datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def test_missed_runs_ignored_by_default(app, db, py_task):
    now = datetime(2026, 11, 16, 12, 10, tzinfo=UTC)
    t = py_task("print(1)", cron_expressions=["*/30 * * * *"])
    _setup_downtime(db, t["id"], now, "ignore")
    _clocked_engine(app, now).recover()
    db.expire_all()
    assert db.scalars(select(Run).where(Run.task_id == t["id"])).all() == []
    assert _task_row(db, t["id"]).last_fire_at == datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def test_no_missed_runs_on_first_start_or_for_paused_tasks(app, client, db, py_task):
    now = datetime(2026, 11, 16, 12, 10, tzinfo=UTC)
    t = py_task("print(1)", cron_expressions=["*/30 * * * *"], misfire_policy="run_once")
    _clocked_engine(app, now).recover()  # no heartbeat yet: first start
    db.expire_all()
    assert db.scalars(select(Run)).all() == []

    _setup_downtime(db, t["id"], now, "run_once")
    client.patch(f"{API}/tasks/{t['id']}", json={"is_active": False})
    _clocked_engine(app, now).recover()
    db.expire_all()
    assert db.scalars(select(Run)).all() == []

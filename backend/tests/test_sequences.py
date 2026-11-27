"""Sequential subcategories: tasks that inherit the schedule run one after the other."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from rts.engine.context import EngineContext
from rts.engine.scheduler import SchedulerEngine
from rts.models import Run, RunStatus, SequenceRun, SequenceStatus, Subcategory
from tests.conftest import API


@pytest.fixture
def engine(app):
    eng = SchedulerEngine(
        EngineContext(app.state.settings, app.state.session_factory, app.state.secret_box),
        poll_interval=0.1,
    )
    yield eng
    eng.stop(timeout=20)


def step_command(tag: str, exit_code: int = 0, sleep: float = 0.3) -> str:
    """Python task: appends start/end marks to the shared file, then exits."""
    return (
        "import os, time\n"
        "path = os.environ['SEQ_FILE']\n"
        f"open(path, 'a').write('start {tag}\\n')\n"
        f"time.sleep({sleep})\n"
        f"open(path, 'a').write('end {tag}\\n')\n"
        f"raise SystemExit({exit_code})\n"
    )


@pytest.fixture
def seq_sub(make, tmp_path):
    """Sequential subcategory (every 2 h) with steps a, b, c and an own-schedule task."""
    marks = tmp_path / "marks.txt"
    g = make.group("palacio", cron_expressions=["0 */2 * * *"], timezone="UTC")
    s = make.subcategory(g["id"], "relatorios", execution_mode="sequential")
    make.variable("subcategory", "SEQ_FILE", str(marks), owner_id=s["id"])

    def task(name, **kw):
        kw.setdefault("schedule_mode", "inherit")
        kw.setdefault("cron_expressions", [])
        kw.setdefault("command", step_command(name))
        return make.task(s["id"], name, shell="python", **kw)

    tasks = {name: task(name) for name in ("a", "b", "c")}
    tasks["own"] = task("own", schedule_mode="own", cron_expressions=["0 14 * * *"])
    return {"sub": s, "tasks": tasks, "marks": marks, "task": task}


def drive(engine, db, seq_id: int, timeout: float = 60.0) -> SequenceRun:
    """Run the engine loop by hand until the sequence finishes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        engine.tick()
        engine.wait_idle(30)
        db.expire_all()
        seq = db.get(SequenceRun, seq_id)
        if seq.status is not SequenceStatus.RUNNING:
            return seq
        time.sleep(0.05)
    raise AssertionError("sequence did not finish in time")


def runs_of(db, seq_id: int) -> list[Run]:
    db.expire_all()
    return list(db.scalars(select(Run).where(Run.sequence_run_id == seq_id).order_by(Run.id)))


def start(client, sub_id: int) -> dict:
    resp = client.post(f"{API}/subcategories/{sub_id}/sequences")
    assert resp.status_code == 202, resp.text
    return resp.json()


# =========================================================================== API
def test_settings_order_and_task_positions(client, seq_sub):
    sub, t = seq_sub["sub"], seq_sub["tasks"]
    assert sub["execution_mode"] == "sequential" and sub["stop_on_failure"] is False
    # Default order: by name. Own-schedule tasks are not part of the sequence.
    a = client.get(f"{API}/tasks/{t['a']['id']}").json()
    assert (a["sequence_step"], a["sequence_total"]) == (1, 3)
    assert client.get(f"{API}/tasks/{t['own']['id']}").json()["sequence_step"] is None

    resp = client.put(
        f"{API}/subcategories/{sub['id']}/sequence-order",
        json={"task_ids": [t["c"]["id"], t["a"]["id"], t["b"]["id"]]},
    )
    assert resp.json()["task_ids"] == [t["c"]["id"], t["a"]["id"], t["b"]["id"]]
    assert client.get(f"{API}/tasks/{t['c']['id']}").json()["sequence_step"] == 1

    bad = client.put(f"{API}/subcategories/{sub['id']}/sequence-order", json={"task_ids": [999]})
    assert bad.status_code == 422

    body = client.patch(
        f"{API}/subcategories/{sub['id']}", json={"execution_mode": "parallel"}
    ).json()
    assert body["execution_mode"] == "parallel"
    assert client.get(f"{API}/tasks/{t['a']['id']}").json()["sequence_step"] is None
    assert client.post(f"{API}/subcategories/{sub['id']}/sequences").status_code == 422


# =========================================================================== engine
def test_engine_schedules_one_job_for_the_sequence(engine, client, seq_sub):
    sub, t = seq_sub["sub"], seq_sub["tasks"]
    engine.reload_jobs(force=True)
    keys = set(engine._job_signatures)
    assert keys == {f"seq-{sub['id']}", t["own"]["id"]}
    assert engine._job_signatures[f"seq-{sub['id']}"] == (("0 */2 * * *",), "UTC")
    # A stale task job firing for a task of the sequence does nothing.
    assert engine.on_fire(t["a"]["id"], datetime.now(UTC)) is None

    client.patch(f"{API}/subcategories/{sub['id']}", json={"execution_mode": "parallel"})
    engine.reload_jobs()
    assert set(engine._job_signatures) == {t["a"]["id"], t["b"]["id"], t["c"]["id"], t["own"]["id"]}


def test_steps_run_in_order_one_at_a_time(engine, client, db, seq_sub):
    sub, t = seq_sub["sub"], seq_sub["tasks"]
    client.put(
        f"{API}/subcategories/{sub['id']}/sequence-order",
        json={"task_ids": [t["c"]["id"], t["a"]["id"], t["b"]["id"]]},
    )
    seq = start(client, sub["id"])
    assert seq["total_steps"] == 3 and seq["steps"][0]["task_name"] == "c"
    assert client.get(f"{API}/subcategories/{sub['id']}").json()["running_sequence_id"] == seq["id"]

    done = drive(engine, db, seq["id"])
    assert (
        done.status is SequenceStatus.SUCCESS
        and done.status_reason == "3 de 3 tarefas com sucesso."
    )
    marks = seq_sub["marks"].read_text().split("\n")
    assert [m for m in marks if m] == ["start c", "end c", "start a", "end a", "start b", "end b"]
    runs = runs_of(db, seq["id"])
    assert [r.sequence_index for r in runs] == [0, 1, 2]
    assert all(runs[i + 1].started_at >= runs[i].finished_at for i in range(2))

    body = client.get(f"{API}/sequences/{seq['id']}").json()
    assert body["completed_steps"] == 3 and [s["status"] for s in body["steps"]] == ["success"] * 3
    run = client.get(f"{API}/runs/{runs[1].id}").json()
    assert (run["sequence_run_id"], run["sequence_index"], run["sequence_total"]) == (
        seq["id"],
        1,
        3,
    )
    assert "Etapa 2 de 3 da sequência" in client.get(f"{API}/runs/{runs[1].id}/log.txt").text


def test_failure_continues_by_default(engine, client, db, seq_sub):
    sub, t = seq_sub["sub"], seq_sub["tasks"]
    client.patch(f"{API}/tasks/{t['b']['id']}", json={"command": step_command("b", exit_code=3)})
    seq = start(client, sub["id"])
    done = drive(engine, db, seq["id"])
    assert (
        done.status is SequenceStatus.FAILED and done.status_reason == "2 de 3 tarefas com sucesso."
    )
    assert [r.status for r in runs_of(db, seq["id"])] == [
        RunStatus.SUCCESS,
        RunStatus.FAILED,
        RunStatus.SUCCESS,
    ]


def test_stop_on_failure(engine, client, db, seq_sub):
    sub, t = seq_sub["sub"], seq_sub["tasks"]
    client.patch(f"{API}/subcategories/{sub['id']}", json={"stop_on_failure": True})
    client.patch(f"{API}/tasks/{t['b']['id']}", json={"command": step_command("b", exit_code=3)})
    seq = start(client, sub["id"])
    done = drive(engine, db, seq["id"])
    assert done.status is SequenceStatus.FAILED
    assert done.status_reason == "Parou na etapa 2 (b): falha."
    assert len(runs_of(db, seq["id"])) == 2
    steps = client.get(f"{API}/sequences/{seq['id']}").json()["steps"]
    assert [s["status"] for s in steps] == ["success", "failed", "not_run"]


def test_sequence_waits_for_retries(engine, client, db, seq_sub, tmp_path):
    sub, t = seq_sub["sub"], seq_sub["tasks"]
    flag = tmp_path / "second-try"
    flaky = (
        "import os, pathlib\n"
        f"flag = pathlib.Path({str(flag)!r})\n"
        "open(os.environ['SEQ_FILE'], 'a').write('try a\\n')\n"
        "if not flag.exists():\n"
        "    flag.write_text('x')\n"
        "    raise SystemExit(1)\n"
    )
    client.patch(
        f"{API}/tasks/{t['a']['id']}",
        json={"command": flaky, "max_retries": 1, "retry_interval_seconds": 0},
    )
    seq = start(client, sub["id"])
    done = drive(engine, db, seq["id"])
    assert done.status is SequenceStatus.SUCCESS
    runs = runs_of(db, seq["id"])
    assert [(r.sequence_index, r.attempt, r.status) for r in runs] == [
        (0, 1, RunStatus.FAILED),
        (0, 2, RunStatus.SUCCESS),
        (1, 1, RunStatus.SUCCESS),
        (2, 1, RunStatus.SUCCESS),
    ]
    assert seq_sub["marks"].read_text().split("\n")[:2] == ["try a", "try a"]
    step = client.get(f"{API}/sequences/{seq['id']}").json()["steps"][0]
    assert (step["status"], step["attempt"]) == ("success", 2)


def test_fire_while_running_is_skipped_and_cancel_stops(engine, client, db, seq_sub):
    sub, t = seq_sub["sub"], seq_sub["tasks"]
    client.patch(f"{API}/tasks/{t['a']['id']}", json={"command": step_command("a", sleep=30)})
    seq = start(client, sub["id"])
    assert client.post(f"{API}/subcategories/{sub['id']}/sequences").status_code == 409

    engine.tick()  # starts step a (30 s)
    fired = engine.on_sequence_fire(sub["id"], datetime.now(UTC))
    assert (
        fired.status is SequenceStatus.SKIPPED and "ainda está em andamento" in fired.status_reason
    )
    # A repeated fire for the same time is ignored.
    db.expire_all()
    last_fire = db.get(Subcategory, sub["id"]).last_sequence_fire_at
    assert engine.on_sequence_fire(sub["id"], last_fire) is None

    resp = client.post(f"{API}/sequences/{seq['id']}/cancel")
    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
    engine.wait_idle(30)
    engine.tick()
    runs = runs_of(db, seq["id"])
    assert len(runs) == 1 and runs[0].status is RunStatus.CANCELLED
    assert client.post(f"{API}/sequences/{seq['id']}/cancel").status_code == 409


def test_paused_and_deleted_tasks_are_passed_over(engine, client, db, seq_sub):
    sub, t = seq_sub["sub"], seq_sub["tasks"]
    client.patch(f"{API}/tasks/{t['b']['id']}", json={"is_active": False})
    seq = start(client, sub["id"])
    assert [s["task_name"] for s in seq["steps"]] == ["a", "c"]  # paused: not in the sequence

    seq_sub["task"]("d")
    client.post(f"{API}/subcategories/{sub['id']}/sequences")  # 409: one is running
    engine.tick()
    client.delete(f"{API}/tasks/{t['c']['id']}")  # deleted before its turn
    done = drive(engine, db, seq["id"])
    assert [r.task_id for r in runs_of(db, seq["id"])] == [t["a"]["id"]]
    assert done.status is SequenceStatus.FAILED  # the deleted step never ran


def test_dashboard_shows_the_sequence_once(client, seq_sub):
    body = client.get(f"{API}/dashboard").json()
    names = [u["task_name"] for u in body["upcoming"]]
    assert "a (sequência de 3 tarefas)" in names
    assert not any(n in ("b", "c") for n in names)


# =========================================================================== export/import
def test_export_import_keeps_sequence_settings_and_order(client, seq_sub, tmp_path):
    import yaml
    from fastapi.testclient import TestClient

    from rts.db import Base
    from rts.main import create_app
    from tests.conftest import login, make_settings

    sub, t = seq_sub["sub"], seq_sub["tasks"]
    client.patch(f"{API}/subcategories/{sub['id']}", json={"stop_on_failure": True})
    client.put(
        f"{API}/subcategories/{sub['id']}/sequence-order",
        json={"task_ids": [t["c"]["id"], t["a"]["id"], t["b"]["id"]]},
    )
    content = client.post(f"{API}/transfer/export", json={"scope": "system"}).text
    doc = yaml.safe_load(content)
    assert doc["schema_version"] == 3
    exported = doc["groups"][0]["subcategories"][0]
    assert exported["execution"] == {"mode": "sequential", "stop_on_failure": True}
    positions = {task["name"]: task.get("sequence_position") for task in exported["tasks"]}
    assert positions == {"a": 2, "b": 3, "c": 1, "own": None}

    app = create_app(make_settings(tmp_path / "other"))
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as other:
        login(other)
        report = other.post(f"{API}/transfer/import/preview", json={"content": content}).json()
        details = [d for i in report["items"] if i["kind"] == "subcategory" for d in i["details"]]
        assert "execução sequencial (para na falha)" in details
        body = {"content": content, "activate_tasks": True}  # imported tasks are paused otherwise
        assert other.post(f"{API}/transfer/import/apply", json=body).json()["applied"]
        imported = other.get(f"{API}/subcategories").json()[0]
        assert (imported["execution_mode"], imported["stop_on_failure"]) == ("sequential", True)
        steps = {x["name"]: x["sequence_step"] for x in other.get(f"{API}/tasks").json()}
        assert steps == {"c": 1, "a": 2, "b": 3, "own": None}
    app.state.engine.dispose()

    # Without sequences the file stays at the lowest version it needs.
    client.patch(
        f"{API}/subcategories/{sub['id']}",
        json={"execution_mode": "parallel", "stop_on_failure": False},
    )
    client.put(f"{API}/subcategories/{sub['id']}/sequence-order", json={"task_ids": []})
    assert (
        yaml.safe_load(client.post(f"{API}/transfer/export", json={"scope": "system"}).text)[
            "schema_version"
        ]
        == 2
    )  # inherited schedules still need version 2


def test_real_scheduler_fires_the_sequence(app, client, db, seq_sub, monkeypatch):
    """End-to-end: APScheduler fires the "seq-" job -> sequence -> steps executed in order."""
    from apscheduler.triggers.interval import IntervalTrigger

    import rts.engine.scheduler as sched_mod

    monkeypatch.setattr(sched_mod, "build_trigger", lambda *_a, **_k: IntervalTrigger(seconds=1))
    sub = seq_sub["sub"]
    eng = SchedulerEngine(
        EngineContext(app.state.settings, app.state.session_factory, app.state.secret_box),
        poll_interval=0.1,
    )
    eng.start()
    try:
        deadline = time.monotonic() + 60
        seq = None
        while time.monotonic() < deadline:
            db.expire_all()
            seq = db.scalars(
                select(SequenceRun)
                .where(SequenceRun.subcategory_id == sub["id"])
                .where(SequenceRun.status == SequenceStatus.SUCCESS)
            ).first()
            if seq is not None:
                break
            time.sleep(0.2)
        assert seq is not None, "no sequence finished"
        assert seq.trigger.value == "scheduled" and seq.scheduled_for is not None
        assert [r.sequence_index for r in runs_of(db, seq.id)] == [0, 1, 2]
        # Fires while it ran were skipped, never run in parallel.
        db.expire_all()
        others = db.scalars(
            select(SequenceRun).where(
                SequenceRun.subcategory_id == sub["id"], SequenceRun.id != seq.id
            )
        ).all()
        assert all(
            o.status in (SequenceStatus.SKIPPED, SequenceStatus.RUNNING, SequenceStatus.SUCCESS)
            for o in others
        )
    finally:
        eng.stop()


# =========================================================================== run all
def test_run_all_in_a_sequential_subcategory(engine, client, db, seq_sub):
    """All active tasks, one at a time: the sequence order, then the ones outside it."""
    sub, t = seq_sub["sub"], seq_sub["tasks"]
    client.patch(f"{API}/tasks/{t['own']['id']}", json={"command": step_command("own")})
    paused = seq_sub["task"]("pausada")
    client.patch(f"{API}/tasks/{paused['id']}", json={"is_active": False})

    resp = client.post(f"{API}/subcategories/{sub['id']}/run-all")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["mode"] == "sequential" and body["task_count"] == 4
    assert body["paused"] == ["pausada"] and len(body["run_ids"]) == 1
    assert client.post(f"{API}/subcategories/{sub['id']}/run-all").status_code == 409

    done = drive(engine, db, body["sequence_id"])
    assert done.status is SequenceStatus.SUCCESS
    marks = [m for m in seq_sub["marks"].read_text().split("\n") if m.startswith("start")]
    assert marks == ["start a", "start b", "start c", "start own"]


def test_run_all_in_a_parallel_subcategory(engine, client, db, seq_sub):
    sub, t = seq_sub["sub"], seq_sub["tasks"]
    client.patch(f"{API}/subcategories/{sub['id']}", json={"execution_mode": "parallel"})
    client.patch(f"{API}/tasks/{t['own']['id']}", json={"is_active": False})

    body = client.post(f"{API}/subcategories/{sub['id']}/run-all").json()
    assert body["mode"] == "parallel" and body["sequence_id"] is None
    assert body["task_count"] == 3 and body["paused"] == ["own"]
    runs = [db.get(Run, i) for i in body["run_ids"]]
    assert sorted(r.task_id for r in runs) == sorted(t[n]["id"] for n in ("a", "b", "c"))
    assert all(r.trigger.value == "manual" and r.triggered_by == "admin" for r in runs)

    started = engine.dispatch()  # all at once
    assert sorted(started) == sorted(body["run_ids"])
    assert engine.wait_idle(30)
    db.expire_all()
    assert all(db.get(Run, i).status is RunStatus.SUCCESS for i in body["run_ids"])


def test_run_all_without_active_tasks(client, make):
    g = make.group("g")
    s = make.subcategory(g["id"], "vazia")
    assert client.post(f"{API}/subcategories/{s['id']}/run-all").status_code == 422
    assert client.post(f"{API}/subcategories/999/run-all").status_code == 404

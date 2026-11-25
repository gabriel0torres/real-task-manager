"""Interrupting a task's active run, and how long a group's automations take."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rts.models import Run, RunStatus, RunTrigger, SequenceRun, SequenceStatus
from tests.conftest import API

T0 = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


# =========================================================================== active run
def test_task_exposes_the_run_to_interrupt(client, make, db):
    _, _, task = make.tree()
    url = f"{API}/tasks/{task['id']}"
    assert client.get(url).json()["active_run_id"] is None

    queued = client.post(f"{url}/run").json()
    body = client.get(url).json()
    assert (body["active_run_id"], body["active_run_status"]) == (queued["id"], "pending")

    running = db.get(Run, client.post(f"{url}/run").json()["id"])
    running.status, running.started_at = RunStatus.RUNNING, at(0)
    db.commit()
    body = client.get(url).json()  # a running one comes first
    assert (body["active_run_id"], body["active_run_status"]) == (running.id, "running")
    listed = {t["id"]: t for t in client.get(f"{API}/tasks").json()}
    assert listed[task["id"]]["active_run_id"] == running.id

    # "Interromper" = cancel that run; the waiting one remains.
    assert client.post(f"{API}/runs/{running.id}/cancel").json()["cancel_requested"] is True
    client.post(f"{API}/runs/{queued['id']}/cancel")
    running.status = RunStatus.CANCELLED
    db.commit()
    assert client.get(url).json()["active_run_id"] is None


# =========================================================================== execution times
def _run(db, task_id, status, start, end, **kw):
    run = Run(
        task_id=task_id,
        status=status,
        trigger=kw.pop("trigger", RunTrigger.SCHEDULED),
        started_at=start,
        finished_at=end,
        created_at=start or T0,
        **kw,
    )
    db.add(run)
    db.flush()
    return run


def test_sequential_subcategory_times(client, make, db):
    g = make.group("automacoes", cron_expressions=["0 */2 * * *"])
    s = make.subcategory(g["id"], "palacio", execution_mode="sequential")
    a = make.task(s["id"], "a", schedule_mode="inherit", cron_expressions=[])
    b = make.task(s["id"], "b", schedule_mode="inherit", cron_expressions=[])

    def sequence(start, minutes_a, minutes_b, b_status=RunStatus.SUCCESS, status=None):
        seq = SequenceRun(
            subcategory_id=s["id"],
            status=status or SequenceStatus.SUCCESS,
            trigger=RunTrigger.SCHEDULED,
            task_ids=[a["id"], b["id"]],
            current_index=1,
            stop_on_failure=False,
            created_at=at(start),
            finished_at=at(start + minutes_a + minutes_b),
        )
        db.add(seq)
        db.flush()
        _run(
            db,
            a["id"],
            RunStatus.SUCCESS,
            at(start),
            at(start + minutes_a),
            sequence_run_id=seq.id,
            sequence_index=0,
        )
        _run(
            db,
            b["id"],
            b_status,
            at(start + minutes_a),
            at(start + minutes_a + minutes_b),
            sequence_run_id=seq.id,
            sequence_index=1,
        )
        return seq

    sequence(0, 10, 20)  # 30 min
    sequence(120, 15, 25, b_status=RunStatus.FAILED, status=SequenceStatus.FAILED)  # 40 min
    db.add(
        SequenceRun(
            subcategory_id=s["id"],
            status=SequenceStatus.SKIPPED,
            trigger=RunTrigger.SCHEDULED,
            task_ids=[],
            current_index=0,
            stop_on_failure=False,
            created_at=at(130),
            finished_at=at(130),
        )
    )
    running = SequenceRun(
        subcategory_id=s["id"],
        status=SequenceStatus.RUNNING,
        trigger=RunTrigger.SCHEDULED,
        task_ids=[a["id"], b["id"]],
        current_index=0,
        stop_on_failure=False,
        created_at=at(240),
    )
    db.add(running)
    db.flush()
    _run(
        db, a["id"], RunStatus.RUNNING, at(240), None, sequence_run_id=running.id, sequence_index=0
    )
    db.commit()

    body = client.get(f"{API}/groups/{g['id']}/execution-times").json()
    row = body["subcategories"][0]
    assert row["name"] == "palacio" and row["execution_mode"] == "sequential"
    assert row["last"]["duration_ms"] == 40 * 60_000
    assert (row["last"]["status"], row["last"]["succeeded"], row["last"]["total"]) == (
        "failed",
        1,
        2,
    )
    assert row["average_ms"] == 35 * 60_000 and row["average_of"] == 2  # skipped one ignored
    assert row["running"]["sequence_id"] == running.id and row["running"]["duration_ms"] is None
    assert body["total_last_ms"] == 40 * 60_000


def test_parallel_subcategory_rounds(client, make, db):
    g = make.group("infra")
    s = make.subcategory(g["id"], "backups")
    x = make.task(s["id"], "x", cron_expressions=["0 3 * * *"])
    y = make.task(s["id"], "y", cron_expressions=["0 3 * * *"])
    make.task(s["id"], "sem-execucao", cron_expressions=[])

    # Round at 03:00: x 5 min; y fails, then its retry ends 12 min after the start.
    fire = at(180)
    _run(db, x["id"], RunStatus.SUCCESS, at(180), at(185), scheduled_for=fire)
    y1 = _run(db, y["id"], RunStatus.FAILED, at(180), at(182), scheduled_for=fire)
    _run(
        db,
        y["id"],
        RunStatus.SUCCESS,
        at(190),
        at(192),
        trigger=RunTrigger.RETRY,
        attempt=2,
        root_run_id=y1.id,
        scheduled_for=at(190),
    )
    # Manual runs don't count as rounds.
    _run(db, x["id"], RunStatus.SUCCESS, at(300), at(400), trigger=RunTrigger.MANUAL)
    db.commit()

    body = client.get(f"{API}/groups/{g['id']}/execution-times").json()
    row = body["subcategories"][0]
    assert row["execution_mode"] == "parallel"
    assert row["last"]["kind"] == "round" and row["last"]["duration_ms"] == 12 * 60_000
    assert (row["last"]["status"], row["last"]["succeeded"], row["last"]["total"]) == (
        "success",
        2,
        2,
    )
    assert row["running"] is None and row["average_of"] == 1


def test_group_without_runs(client, make):
    g = make.group("vazio")
    make.subcategory(g["id"], "s")
    body = client.get(f"{API}/groups/{g['id']}/execution-times").json()
    assert body["subcategories"][0]["last"] is None and body["total_last_ms"] == 0
    assert client.get(f"{API}/groups/999/execution-times").status_code == 404


# =========================================================================== interrupt the group
def test_interrupt_everything_in_a_group(app, client, make, db):
    import time

    from rts.engine.context import EngineContext
    from rts.engine.scheduler import SchedulerEngine

    sleeper = "import time\ntime.sleep(60)\n"
    g = make.group("automacoes")
    seq_sub = make.subcategory(g["id"], "palacio", execution_mode="sequential")
    for name in ("a", "b"):
        make.task(
            seq_sub["id"],
            name,
            shell="python",
            command=sleeper,
            schedule_mode="inherit",
            cron_expressions=[],
        )
    par_sub = make.subcategory(g["id"], "nacional")
    long_task = make.task(
        par_sub["id"], "longa", shell="python", command=sleeper, cron_expressions=[]
    )
    other_group = make.group("outro")
    outside = make.task(
        make.subcategory(other_group["id"], "s")["id"],
        "fora",
        shell="python",
        command=sleeper,
        cron_expressions=[],
    )

    engine = SchedulerEngine(
        EngineContext(app.state.settings, app.state.session_factory, app.state.secret_box),
        poll_interval=0.1,
    )
    try:
        seq = client.post(f"{API}/subcategories/{seq_sub['id']}/sequences").json()
        client.post(f"{API}/tasks/{long_task['id']}/run")
        queued = client.post(
            f"{API}/tasks/{long_task['id']}/run"
        ).json()  # waits (overlap: skip/queue)
        fora = client.post(f"{API}/tasks/{outside['id']}/run").json()
        engine.dispatch()
        time.sleep(0.5)

        activity = client.get(f"{API}/groups/{g['id']}/execution-times").json()["activity"]
        assert activity["running_sequences"] == 1 and activity["running_runs"] == 2

        result = client.post(f"{API}/groups/{g['id']}/interrupt").json()
        assert result["sequences_cancelled"] == 1 and result["runs_cancelled"] >= 2
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            db.expire_all()
            active = (
                db.query(Run).filter(Run.status.in_([RunStatus.RUNNING, RunStatus.PENDING])).all()
            )
            if [r.task_id for r in active] == [outside["id"]]:
                break
            time.sleep(0.2)
        assert [r.task_id for r in active] == [outside["id"]]  # the other group keeps running
        assert db.get(SequenceRun, seq["id"]).status is SequenceStatus.CANCELLED
        assert db.get(Run, queued["id"]).status in (RunStatus.CANCELLED, RunStatus.SKIPPED)
        engine.tick()  # the cancelled sequence starts nothing else
        db.expire_all()
        assert db.query(Run).filter(Run.sequence_run_id == seq["id"]).count() == 1
        after = client.get(f"{API}/groups/{g['id']}/execution-times").json()["activity"]
        assert after == {"running_sequences": 0, "running_runs": 0, "waiting_runs": 0}
        assert db.get(Run, fora["id"]).status is RunStatus.RUNNING
    finally:
        engine.stop(timeout=20)

    assert client.post(f"{API}/groups/999/interrupt").status_code == 404

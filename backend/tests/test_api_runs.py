from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from rts.config import Settings
from rts.db import Base
from rts.main import create_app
from rts.models import RunStatus, RunTrigger, WorkerHeartbeat
from rts.services.runs import append_system_log, create_run
from tests.conftest import API


def _task(make, **kw):
    g = make.group()
    s = make.subcategory(g["id"])
    return make.task(s["id"], shell="python", command="print('hi')", cron_expressions=[], **kw)


def _finished_run(db, task_id, status=RunStatus.SUCCESS, minutes_ago=0, lines=("a\n", "b\n")):
    run = create_run(db, task_id, RunTrigger.MANUAL)
    run.created_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    run.status = status
    run.finished_at = datetime.now(UTC)
    for line in lines:
        append_system_log(db, run.id, line.strip())
        db.flush()
    db.commit()
    return run


def test_run_now_creates_pending_manual_run(client, make):
    t = _task(make)
    resp = client.post(f"{API}/tasks/{t['id']}/run")
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending" and body["trigger"] == "manual"
    assert body["task_name"] == t["name"] and body["attempt"] == 1
    assert client.post(f"{API}/tasks/999/run").status_code == 404


def test_run_now_allowed_on_paused_task(client, make):
    t = _task(make, is_active=False)
    assert client.post(f"{API}/tasks/{t['id']}/run").status_code == 202


def test_cancel_pending_and_finished(client, make, db):
    t = _task(make)
    run_id = client.post(f"{API}/tasks/{t['id']}/run").json()["id"]
    body = client.post(f"{API}/runs/{run_id}/cancel").json()
    assert body["status"] == "cancelled" and body["status_reason"] == "Cancelada antes de iniciar."
    resp = client.post(f"{API}/runs/{run_id}/cancel")
    assert resp.status_code == 409
    assert client.post(f"{API}/runs/999/cancel").status_code == 404


def test_list_runs_filters_and_pagination(client, make, db):
    t1 = _task(make)
    s2 = make.subcategory(t1["group_id"], "outra")
    t2 = make.task(s2["id"], "t2", command="x", cron_expressions=[])
    _finished_run(db, t1["id"], RunStatus.SUCCESS, minutes_ago=60)
    _finished_run(db, t1["id"], RunStatus.FAILED, minutes_ago=30)
    _finished_run(db, t2["id"], RunStatus.TIMEOUT, minutes_ago=5)

    page = client.get(f"{API}/runs").json()
    assert page["total"] == 3
    assert [r["status"] for r in page["items"]] == ["timeout", "failed", "success"]  # newest first

    by_task = client.get(f"{API}/runs", params={"task_id": t1["id"]}).json()
    assert by_task["total"] == 2

    by_status = client.get(f"{API}/runs", params=[("status", "failed"), ("status", "timeout")])
    assert {r["status"] for r in by_status.json()["items"]} == {"failed", "timeout"}

    since = (datetime.now(UTC) - timedelta(minutes=45)).isoformat()
    assert client.get(f"{API}/runs", params={"since": since}).json()["total"] == 2

    paged = client.get(f"{API}/runs", params={"limit": 1, "offset": 1}).json()
    assert paged["total"] == 3 and len(paged["items"]) == 1
    assert paged["items"][0]["status"] == "failed"

    assert client.get(f"{API}/runs", params={"status": "bogus"}).status_code == 422


def test_log_endpoints(client, make, db):
    t = _task(make)
    run = _finished_run(db, t["id"], lines=("primeira", "segunda", "terceira"))
    body = client.get(f"{API}/runs/{run.id}/log").json()
    assert body["status"] == "success"
    assert [c["seq"] for c in body["chunks"]] == [1, 2, 3]
    assert body["chunks"][0]["stream"] == "system"

    after = client.get(f"{API}/runs/{run.id}/log", params={"after_seq": 2}).json()
    assert [c["content"] for c in after["chunks"]] == ["[RTS] terceira\n"]

    text = client.get(f"{API}/runs/{run.id}/log.txt")
    assert text.headers["content-type"].startswith("text/plain")
    assert text.text == "[RTS] primeira\n[RTS] segunda\n[RTS] terceira\n"
    assert client.get(f"{API}/runs/999/log").status_code == 404


def _read_sse(client, url, **kw):
    events = []
    with client.stream("GET", url, **kw) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        event = {}
        for line in resp.iter_lines():
            if not line:
                if event:
                    events.append(event)
                    if event.get("event") == "end":
                        break
                event = {}
                continue
            if line.startswith(":"):
                continue
            key, _, value = line.partition(": ")
            event[key] = value
    return events


def test_sse_stream_of_finished_run(client, make, db):
    t = _task(make)
    run = _finished_run(db, t["id"], lines=("um", "dois"))
    events = _read_sse(client, f"{API}/runs/{run.id}/log/stream")
    logs = [e for e in events if e["event"] == "log"]
    assert [json.loads(e["data"])["content"] for e in logs] == ["[RTS] um\n", "[RTS] dois\n"]
    assert [e["id"] for e in logs] == ["1", "2"]
    assert any(
        e["event"] == "status" and json.loads(e["data"])["status"] == "success" for e in events
    )
    assert events[-1]["event"] == "end"

    resumed = _read_sse(client, f"{API}/runs/{run.id}/log/stream", headers={"Last-Event-ID": "1"})
    assert [e["id"] for e in resumed if e["event"] == "log"] == ["2"]
    assert client.get(f"{API}/runs/999/log/stream").status_code == 404


def test_worker_status(client, db):
    assert client.get(f"{API}/system/worker").json()["online"] is False
    now = datetime.now(UTC)
    db.add(WorkerHeartbeat(worker_id="w1", started_at=now, last_seen=now, version="x"))
    db.commit()
    body = client.get(f"{API}/system/worker").json()
    assert body["online"] is True and body["worker_id"] == "w1"


def test_embedded_worker_runs_task_end_to_end(tmp_path, settings):
    embedded = Settings(**{**settings.model_dump(), "embedded_worker": True}, _env_file=None)
    app = create_app(embedded)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        g = client.post(f"{API}/groups", json={"name": "g"}).json()
        s = client.post(f"{API}/subcategories", json={"group_id": g["id"], "name": "s"}).json()
        t = client.post(
            f"{API}/tasks",
            json={
                "subcategory_id": s["id"],
                "name": "t",
                "shell": "python",
                "command": "print('live output')",
            },
        ).json()
        run_id = client.post(f"{API}/tasks/{t['id']}/run").json()["id"]

        events = _read_sse(client, f"{API}/runs/{run_id}/log/stream")
        statuses = [json.loads(e["data"])["status"] for e in events if e["event"] == "status"]
        assert statuses[-1] == "success"
        assert any("live output" in e.get("data", "") for e in events if e["event"] == "log")

        deadline = time.monotonic() + 5
        while (
            time.monotonic() < deadline and not client.get(f"{API}/system/worker").json()["online"]
        ):
            time.sleep(0.1)
        assert client.get(f"{API}/system/worker").json()["online"] is True

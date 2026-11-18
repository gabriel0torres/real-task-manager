"""Schedules inherited from the subcategory or group (task schedule modes)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
import yaml
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select

from rts.db import Base, make_engine
from rts.engine.context import EngineContext
from rts.engine.scheduler import SchedulerEngine
from rts.main import create_app
from rts.migrations.runner import alembic_config
from rts.models import Run, Task, WorkerHeartbeat
from tests.conftest import API, login, make_settings

HOURLY_2 = "0 */2 * * *"


def get_task(client, task_id: int) -> dict:
    resp = client.get(f"{API}/tasks/{task_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def tree(make):
    """Group (every 2 h) > subcategory without schedule > three tasks, one per mode."""
    g = make.group("clientes", cron_expressions=[HOURLY_2], timezone="UTC")
    s = make.subcategory(g["id"], "cliente-x")
    inherit = make.task(s["id"], "relatorio", schedule_mode="inherit", cron_expressions=[])
    own = make.task(s["id"], "conciliacao", schedule_mode="own", cron_expressions=["0 14 * * *"])
    manual = make.task(s["id"], "limpeza", schedule_mode="manual", cron_expressions=[])
    return {"group": g, "sub": s, "inherit": inherit, "own": own, "manual": manual}


# =========================================================================== API
def test_group_and_subcategory_carry_a_schedule(client, tree):
    g = tree["group"]
    assert g["cron_expressions"] == [HOURLY_2] and g["timezone"] == "UTC"
    assert g["schedule_description"]
    sub = client.get(f"{API}/subcategories/{tree['sub']['id']}").json()
    assert sub["cron_expressions"] == [] and sub["schedule_description"]
    assert sub["inherited_schedule"]["source"] == "group"
    assert sub["inherited_schedule"]["cron_expressions"] == [HOURLY_2]

    bad = client.patch(f"{API}/groups/{g['id']}", json={"cron_expressions": ["0 8 * *"]})
    assert bad.status_code == 422
    bad = client.patch(f"{API}/groups/{g['id']}", json={"timezone": "Lua/Base"})
    assert bad.status_code == 422


def test_task_modes_and_effective_schedule(client, tree):
    inherit = tree["inherit"]
    assert inherit["schedule_mode"] == "inherit"
    assert inherit["schedule_source"] == "group"
    assert inherit["effective_cron_expressions"] == [HOURLY_2]
    assert inherit["effective_timezone"] == "UTC"
    assert inherit["next_run_at"] is not None
    assert inherit["next_run_at"].endswith(":00:00Z") or "+00:00" in inherit["next_run_at"]

    own = tree["own"]
    assert own["schedule_source"] == "task" and own["effective_cron_expressions"] == ["0 14 * * *"]

    manual = tree["manual"]
    assert manual["schedule_source"] == "manual" and manual["next_run_at"] is None
    assert manual["effective_cron_expressions"] == []


def test_subcategory_schedule_wins_over_group_and_changes_follow(client, tree):
    sub_id, inherit_id = tree["sub"]["id"], tree["inherit"]["id"]
    resp = client.patch(
        f"{API}/subcategories/{sub_id}",
        json={"cron_expressions": ["0 8 * * *"], "timezone": "America/Sao_Paulo"},
    )
    assert resp.status_code == 200
    assert resp.json()["inherited_schedule"]["source"] == "subcategory"

    task = get_task(client, inherit_id)
    assert task["schedule_source"] == "subcategory"
    assert task["effective_cron_expressions"] == ["0 8 * * *"]
    assert task["effective_timezone"] == "America/Sao_Paulo"
    # 08:00 in São Paulo (UTC-3) = 11:00 UTC
    assert datetime.fromisoformat(task["next_run_at"]).astimezone(UTC).hour == 11

    # The task with its own schedule is not affected.
    assert get_task(client, tree["own"]["id"])["effective_cron_expressions"] == ["0 14 * * *"]

    # Clearing the subcategory schedule falls back to the group's.
    client.patch(f"{API}/subcategories/{sub_id}", json={"cron_expressions": [], "timezone": None})
    assert get_task(client, inherit_id)["schedule_source"] == "group"

    # And without any schedule above, an inheriting task only runs manually.
    client.patch(f"{API}/groups/{tree['group']['id']}", json={"cron_expressions": []})
    task = get_task(client, inherit_id)
    assert task["schedule_source"] == "none" and task["next_run_at"] is None


def test_own_mode_requires_expressions(client, make, tree):
    resp = client.post(
        f"{API}/tasks",
        json={
            "subcategory_id": tree["sub"]["id"],
            "name": "sem-horario",
            "command": "echo",
            "schedule_mode": "own",
            "cron_expressions": [],
        },
    )
    assert resp.status_code == 422 and "agendamento próprio" in resp.json()["detail"]

    resp = client.patch(f"{API}/tasks/{tree['manual']['id']}", json={"schedule_mode": "own"})
    assert resp.status_code == 422
    assert get_task(client, tree["manual"]["id"])["schedule_mode"] == "manual"


def test_inheriting_keeps_the_own_schedule_for_later(client, tree):
    own_id = tree["own"]["id"]
    resp = client.patch(f"{API}/tasks/{own_id}", json={"schedule_mode": "inherit"})
    body = resp.json()
    assert body["schedule_source"] == "group" and body["cron_expressions"] == ["0 14 * * *"]
    body = client.patch(f"{API}/tasks/{own_id}", json={"schedule_mode": "own"}).json()
    assert body["schedule_source"] == "task" and body["effective_cron_expressions"] == [
        "0 14 * * *"
    ]


def test_clients_without_schedule_mode_keep_the_old_meaning(client, make, tree):
    """Before schedule modes: a schedule meant "own", an empty one "manual"."""
    sub_id = tree["sub"]["id"]
    scheduled = make.task(sub_id, "antiga", cron_expressions=["0 6 * * *"])
    assert scheduled["schedule_mode"] == "own"
    manual = make.task(sub_id, "antiga-manual", cron_expressions=[])
    assert manual["schedule_mode"] == "manual"

    body = client.patch(f"{API}/tasks/{scheduled['id']}", json={"cron_expressions": []}).json()
    assert body["schedule_mode"] == "manual"
    body = client.patch(f"{API}/tasks/{manual['id']}", json={"cron_expressions": ["0 7 * * *"]})
    assert body.json()["schedule_mode"] == "own"
    # Renaming (no schedule fields) leaves the mode alone.
    body = client.patch(f"{API}/tasks/{tree['inherit']['id']}", json={"name": "relatorio-2"})
    assert body.json()["schedule_mode"] == "inherit"


def test_dashboard_lists_inherited_upcoming_runs(client, tree):
    body = client.get(f"{API}/dashboard").json()
    task_ids = {u["task_id"] for u in body["upcoming"]}
    assert tree["inherit"]["id"] in task_ids and tree["own"]["id"] in task_ids
    assert tree["manual"]["id"] not in task_ids


# =========================================================================== engine
@pytest.fixture
def engine(app):
    eng = SchedulerEngine(
        EngineContext(app.state.settings, app.state.session_factory, app.state.secret_box),
        poll_interval=0.1,
    )
    yield eng
    eng.stop(timeout=20)


def test_engine_schedules_inherited_tasks_and_follows_group_changes(engine, client, tree):
    assert engine.reload_jobs(force=True)
    signatures = engine._job_signatures  # (expressions, time zone) per scheduled task
    assert set(engine.scheduled_jobs()) == {tree["inherit"]["id"], tree["own"]["id"]}
    assert signatures[tree["inherit"]["id"]] == ((HOURLY_2,), "UTC")

    # Changing only the group reschedules the inheriting task.
    client.patch(f"{API}/groups/{tree['group']['id']}", json={"cron_expressions": ["15 3 * * *"]})
    assert engine.reload_jobs() is True
    assert signatures[tree["inherit"]["id"]] == (("15 3 * * *",), "UTC")

    # Without a schedule above, the inheriting task is unscheduled.
    client.patch(f"{API}/groups/{tree['group']['id']}", json={"cron_expressions": []})
    assert engine.reload_jobs() is True
    assert set(signatures) == {tree["own"]["id"]}


def test_on_fire_and_missed_runs_use_the_inherited_schedule(app, db, tree):
    now = datetime(2026, 11, 16, 12, 10, tzinfo=UTC)
    task = db.get(Task, tree["inherit"]["id"])
    task.created_at = now - timedelta(days=1)
    task.misfire_policy = "run_once"
    db.add(
        WorkerHeartbeat(
            worker_id="old",
            started_at=now - timedelta(days=1),
            last_seen=now - timedelta(hours=4, minutes=5),
            version="0",
        )
    )
    db.commit()
    ctx = EngineContext(
        app.state.settings, app.state.session_factory, app.state.secret_box, clock=lambda: now
    )
    SchedulerEngine(ctx).recover()
    db.expire_all()
    runs = db.scalars(select(Run).where(Run.task_id == task.id)).all()
    # every 2 h from the group: 08:00, 10:00, 12:00 missed -> executed once
    assert len(runs) == 1 and runs[0].scheduled_for == datetime(2026, 11, 16, 12, 0, tzinfo=UTC)

    fired = SchedulerEngine(ctx).on_fire(task.id, datetime(2026, 11, 16, 14, 0, tzinfo=UTC))
    assert fired is not None
    manual = SchedulerEngine(ctx).on_fire(tree["manual"]["id"], now)
    assert manual is None


# =========================================================================== export/import
def _export(client, **body) -> str:
    resp = client.post(f"{API}/transfer/export", json={"scope": "system", **body})
    assert resp.status_code == 200, resp.text
    return resp.text


@pytest.fixture
def other(tmp_path):
    settings = make_settings(tmp_path / "other", default_timezone="UTC")
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        login(client)
        yield client
    app.state.engine.dispose()


def test_export_uses_version_2_only_when_needed(client, make):
    g = make.group("simples")
    s = make.subcategory(g["id"], "s")
    make.task(s["id"], "t", cron_expressions=["0 8 * * *"])
    make.task(s["id"], "m", cron_expressions=[])
    doc = yaml.safe_load(_export(client))
    assert doc["schema_version"] == 1
    assert "schedule" not in doc["groups"][0]
    assert all("mode" not in t["schedule"] for t in doc["groups"][0]["subcategories"][0]["tasks"])

    client.patch(f"{API}/groups/{g['id']}", json={"cron_expressions": [HOURLY_2]})
    doc = yaml.safe_load(_export(client))
    assert doc["schema_version"] == 2 and doc["groups"][0]["schedule"]["cron"] == [HOURLY_2]


def test_round_trip_keeps_modes_and_inherited_schedules(client, other, tree):
    client.patch(f"{API}/tasks/{tree['inherit']['id']}", json={"cron_expressions": ["0 5 * * *"]})
    client.patch(f"{API}/tasks/{tree['inherit']['id']}", json={"schedule_mode": "inherit"})
    content = _export(client)
    doc = yaml.safe_load(content)
    tasks = {t["name"]: t for t in doc["groups"][0]["subcategories"][0]["tasks"]}
    assert tasks["relatorio"]["schedule"]["mode"] == "inherit"
    assert tasks["relatorio"]["schedule"]["cron"] == ["0 5 * * *"]  # kept own schedule
    assert "herdado do grupo" in tasks["relatorio"]["schedule"]["description"]
    assert tasks["limpeza"]["schedule"] == {
        "cron": [],
        "timezone": None,
        "description": tasks["limpeza"]["schedule"]["description"],
    }

    report = other.post(f"{API}/transfer/import/preview", json={"content": content}).json()
    task_details = {i["name"]: i["details"] for i in report["items"] if i["kind"] == "task"}
    assert any("herdado do grupo" in d for d in task_details["relatorio"])

    result = other.post(f"{API}/transfer/import/apply", json={"content": content}).json()
    assert result["applied"], result
    imported = {t["name"]: t for t in other.get(f"{API}/tasks").json()}
    assert imported["relatorio"]["schedule_mode"] == "inherit"
    assert imported["relatorio"]["schedule_source"] == "group"
    assert imported["relatorio"]["effective_cron_expressions"] == [HOURLY_2]
    assert imported["relatorio"]["cron_expressions"] == ["0 5 * * *"]
    assert imported["conciliacao"]["schedule_mode"] == "own"
    assert imported["limpeza"]["schedule_mode"] == "manual"
    group = other.get(f"{API}/groups").json()[0]
    assert group["cron_expressions"] == [HOURLY_2] and group["timezone"] == "UTC"


def test_subcategory_export_carries_the_group_schedule(client, other, tree):
    content = _export(client, scope="subcategory", id=tree["sub"]["id"])
    doc = yaml.safe_load(content)
    assert "schedule" not in doc["groups"][0]
    sub = doc["groups"][0]["subcategories"][0]
    assert sub["schedule"]["cron"] == [HOURLY_2]
    assert "(do grupo clientes)" in sub["schedule"]["description"]

    assert other.post(f"{API}/transfer/import/apply", json={"content": content}).json()["applied"]
    imported = {t["name"]: t for t in other.get(f"{API}/tasks").json()}
    assert imported["relatorio"]["schedule_source"] == "subcategory"
    assert imported["relatorio"]["effective_cron_expressions"] == [HOURLY_2]


def test_import_merge_keeps_and_overwrite_clears_a_missing_schedule(client, make):
    g = make.group("sem-agenda")
    content = _export(client, scope="group", id=g["id"])
    assert "schedule" not in yaml.safe_load(content)["groups"][0]
    client.patch(f"{API}/groups/{g['id']}", json={"cron_expressions": [HOURLY_2]})
    path = "group:sem-agenda"

    def apply(action):
        body = {"content": content, "resolutions": {path: {"action": action}}}
        result = client.post(f"{API}/transfer/import/apply", json=body).json()
        assert result["applied"], result
        return client.get(f"{API}/groups/{g['id']}").json()

    assert apply("merge")["cron_expressions"] == [HOURLY_2]
    assert apply("overwrite")["cron_expressions"] == []


def test_invalid_mode_in_file_is_rejected(client):
    content = yaml.safe_dump(
        {
            "schema_version": 2,
            "rts_version": "0.3.0",
            "exported_at": "2026-11-18T00:00:00Z",
            "scope": "system",
            "secrets_mode": "omit",
            "groups": [
                {
                    "name": "g",
                    "subcategories": [
                        {
                            "name": "s",
                            "tasks": [
                                {"name": "t", "command": "echo", "schedule": {"mode": "own"}}
                            ],
                        }
                    ],
                }
            ],
        }
    )
    report = client.post(f"{API}/transfer/import/preview", json={"content": content}).json()
    assert report["valid"] is False
    assert any("'own' exige" in e for e in report["errors"])


# =========================================================================== migration
def _upgrade(engine, revision: str) -> None:
    cfg = alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)


def test_migration_turns_empty_schedules_into_manual_mode(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'mig.db').as_posix()}")
    _upgrade(engine, "0002")
    now = datetime.now(UTC).isoformat()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO groups (id, name, description, is_active, created_at, updated_at)"
            f" VALUES (1, 'g', '', 1, '{now}', '{now}')"
        )
        conn.exec_driver_sql(
            "INSERT INTO subcategories (id, group_id, name, description, is_active,"
            f" created_at, updated_at) VALUES (1, 1, 's', '', 1, '{now}', '{now}')"
        )
        for task_id, crons in ((1, '["0 8 * * *"]'), (2, "[]")):
            conn.exec_driver_sql(
                "INSERT INTO tasks (id, subcategory_id, name, description, command,"
                " cron_expressions, max_retries, retry_interval_seconds, overlap_policy,"
                " misfire_policy, is_active, created_at, updated_at) VALUES"
                f" ({task_id}, 1, 't{task_id}', '', 'echo', '{crons}', 0, 60, 'skip', 'ignore',"
                f" 1, '{now}', '{now}')"
            )
    _upgrade(engine, "head")
    with engine.connect() as conn:
        modes = dict(conn.execute(sa.text("SELECT id, schedule_mode FROM tasks")).all())
        group = conn.execute(sa.text("SELECT cron_expressions, timezone FROM groups")).one()
    assert modes == {1: "own", 2: "manual"}
    assert yaml.safe_load(group[0]) == [] and group[1] is None
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        # the case-insensitive unique index survived the migration
        conn.exec_driver_sql(
            "INSERT INTO tasks (subcategory_id, name, description, command, cron_expressions,"
            " schedule_mode, max_retries, retry_interval_seconds, overlap_policy,"
            " misfire_policy, is_active, created_at, updated_at) VALUES"
            f" (1, 'T1', '', 'echo', '[]', 'manual', 0, 60, 'skip', 'ignore', 1, '{now}', '{now}')"
        )
    engine.dispose()

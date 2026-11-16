import warnings

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from rts import __version__
from rts.config import Settings
from rts.db import Base
from rts.main import create_app
from tests.conftest import API


def test_health(client):
    assert client.get(f"{API}/health").json() == {"status": "ok", "version": __version__}


def test_openapi_docs_available(client):
    assert client.get("/api/docs").status_code == 200
    paths = client.get("/api/openapi.json").json()["paths"]
    assert f"{API}/tasks/{{task_id}}/effective-variables" in paths


def test_schedule_preview_valid(client):
    resp = client.post(
        f"{API}/schedule/preview",
        json={"cron_expressions": ["30 8 * * 1"], "timezone": "UTC", "count": 3},
    )
    body = resp.json()
    assert body["valid"] is True and body["timezone"] == "UTC"
    assert len(body["next_runs"]) == 3
    assert all(r.endswith("08:30:00Z") or "08:30:00+00:00" in r for r in body["next_runs"])


def test_schedule_preview_uses_default_timezone_and_reports_errors(client):
    body = client.post(f"{API}/schedule/preview", json={"cron_expressions": ["0 8 * *"]}).json()
    assert body["valid"] is False and "5 campos" in body["error"]
    assert body["timezone"] == "America/Sao_Paulo" and body["next_runs"] == []


def test_migrations_build_schema_matching_models(tmp_path, settings):
    migrated = Settings(**{**settings.model_dump(), "auto_migrate": True}, _env_file=None)
    app = create_app(migrated)
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        engine = app.state.engine
        tables = set(inspect(engine).get_table_names())
        assert {"groups", "subcategories", "tasks", "variables", "runs", "run_log_chunks"} <= tables

        with engine.connect() as conn, warnings.catch_warnings():
            # SQLite can't reflect expression indexes; they are checked by the INSERT below.
            warnings.simplefilter("ignore")
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == [], diff

        # case-insensitive unique index exists in the migrated database
        client.post(f"{API}/groups", json={"name": "Abc"})
        with engine.begin() as conn:
            try:
                conn.exec_driver_sql(
                    "INSERT INTO groups (name, description, is_active, created_at, updated_at)"
                    " VALUES ('ABC', '', 1, '2026-01-01', '2026-01-01')"
                )
                raised = False
            except Exception:
                raised = True
        assert raised

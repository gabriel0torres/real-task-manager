"""New-version check and update requests (GitHub is simulated)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from rts import __version__
from rts.db import Base
from rts.main import create_app
from rts.models.base import utcnow
from rts.services import updates
from tests.conftest import API, login, make_settings


def test_version_parsing_and_comparison():
    assert updates.parse_version("v1.2.3") == (1, 2, 3)
    assert updates.parse_version("0.10.0") == (0, 10, 0)
    assert updates.parse_version("v1.2.3-rc1") is None
    assert updates.is_newer("v0.10.0", "0.9.9") and not updates.is_newer("v0.1.0", "0.1.0")
    assert not updates.is_newer("lixo", "0.1.0")


def _release(tag="v99.0.0"):
    return {
        "tag": tag,
        "version": tag.lstrip("v"),
        "url": f"https://github.com/x/y/releases/tag/{tag}",
        "notes": "- novidade",
        "published_at": "2026-11-20T10:00:00Z",
    }


@pytest.fixture
def github(monkeypatch):
    calls = {"n": 0, "release": _release(), "error": None}

    def fake(repo, timeout=8.0):
        calls["n"] += 1
        if calls["error"]:
            raise updates.UpdateCheckError(calls["error"])
        return calls["release"]

    monkeypatch.setattr(updates, "fetch_latest", fake)
    return calls


@pytest.fixture
def app_with(tmp_path):
    """Factory: app + logged client with custom update settings."""
    created = []

    def build(**overrides):
        settings = make_settings(
            tmp_path / f"d{len(created)}", **{"update_check": True, **overrides}
        )
        app = create_app(settings)
        Base.metadata.create_all(app.state.engine)
        client = TestClient(app)
        client.__enter__()
        login(client)
        created.append((app, client))
        return app, client

    yield build
    for app, client in created:
        client.__exit__(None, None, None)
        app.state.engine.dispose()


def test_status_reports_new_version_and_caches(app_with, github):
    app, client = app_with(install_type="python", updater="windows-task")
    body = client.get(f"{API}/system/update").json()
    assert body["current_version"] == __version__
    assert body["update_available"] is True and body["latest_version"] == "99.0.0"
    assert body["release_notes"] == "- novidade" and body["can_self_update"] is True
    assert body["install_type"] == "python"

    client.get(f"{API}/system/update")
    assert github["n"] == 1  # cached for 12 h
    client.post(f"{API}/settings/update/check")
    assert github["n"] == 2  # forced


def test_same_version_and_errors(app_with, github):
    app, client = app_with()
    github["release"] = _release(f"v{__version__}")
    body = client.get(f"{API}/system/update").json()
    assert body["update_available"] is False and body["release_notes"] is None
    assert body["install_type"] == "source" and body["can_self_update"] is False
    assert "git pull" in body["instructions"]

    github["error"] = "Sem acesso ao GitHub: timeout"
    body = client.post(f"{API}/settings/update/check").json()
    assert body["error"] == "Sem acesso ao GitHub: timeout"
    assert body["latest_version"] == __version__  # last good answer kept


def test_check_can_be_disabled(app_with, github):
    app, client = app_with(update_check=False, install_type="docker")
    body = client.get(f"{API}/system/update").json()
    assert github["n"] == 0 and body["check_enabled"] is False
    assert "docker compose up -d --build" in body["instructions"]


def test_stale_cache_is_refreshed(app_with, github):
    app, client = app_with()
    client.get(f"{API}/system/update")
    with app.state.session_factory() as s:
        status = updates._cached(s)
        status["checked_at"] = (utcnow() - timedelta(hours=13)).isoformat()
        updates.set_setting(s, updates.STATUS_KEY, status)
        s.commit()
    client.get(f"{API}/system/update")
    assert github["n"] == 2


def test_apply_writes_request_and_starts_windows_task(app_with, github, monkeypatch):
    started = []
    monkeypatch.setattr(updates, "_trigger_windows_task", lambda: started.append(True))
    app, client = app_with(install_type="standalone", updater="windows-task")
    data_dir = app.state.settings.data_dir
    (data_dir / updates.RESULT_FILE).write_text('{"ok": false}')

    resp = client.post(f"{API}/settings/update/apply", json={})
    assert resp.status_code == 202 and resp.json()["version"] == "v99.0.0"
    request = json.loads((data_dir / updates.REQUEST_FILE).read_text())
    assert request["version"] == "v99.0.0" and request["from_version"] == __version__
    assert started == [True]
    assert not (data_dir / updates.RESULT_FILE).exists()  # old result cleared

    status = client.get(f"{API}/system/update").json()
    assert status["update_in_progress"] is True
    resp = client.post(f"{API}/settings/update/apply", json={})
    assert resp.status_code == 409


def test_apply_systemd_only_writes_request(app_with, github):
    app, client = app_with(install_type="python", updater="systemd-path")
    assert (
        client.post(f"{API}/settings/update/apply", json={"version": "v99.0.0"}).status_code == 202
    )
    assert (app.state.settings.data_dir / updates.REQUEST_FILE).exists()


def test_apply_refused_without_updater_or_newer_version(app_with, github):
    app, client = app_with(install_type="docker")
    resp = client.post(f"{API}/settings/update/apply", json={})
    assert resp.status_code == 422 and "não tem atualizador automático" in resp.json()["detail"]

    app2, client2 = app_with(install_type="python", updater="systemd-path")
    resp = client2.post(f"{API}/settings/update/apply", json={"version": "v0.0.1"})
    assert resp.status_code == 422 and "não é mais nova" in resp.json()["detail"]


def test_failed_trigger_removes_request(app_with, github, monkeypatch):
    def boom():
        raise updates.InvalidInputError("tarefa não encontrada")

    monkeypatch.setattr(updates, "_trigger_windows_task", boom)
    app, client = app_with(install_type="python", updater="windows-task")
    resp = client.post(f"{API}/settings/update/apply", json={})
    assert resp.status_code == 422
    assert not (app.state.settings.data_dir / updates.REQUEST_FILE).exists()


def test_last_result_is_reported(app_with, github):
    app, client = app_with(install_type="python", updater="systemd-path")
    (app.state.settings.data_dir / updates.RESULT_FILE).write_text(
        json.dumps({"ok": False, "version": "v99.0.0", "message": "falha no download"})
    )
    body = client.get(f"{API}/system/update").json()
    assert body["last_result"] == {
        "ok": False, "version": "v99.0.0", "from_version": None, "requested_at": None,
        "finished_at": None, "message": "falha no download",
    }  # fmt: skip


def test_real_github_response_parsing(monkeypatch):
    """fetch_latest maps the GitHub payload (network replaced by a fake response)."""
    import io

    payload = {
        "tag_name": "v1.2.3",
        "html_url": "https://github.com/a/b/releases/tag/v1.2.3",
        "body": "notas",
        "published_at": "2026-01-01T00:00:00Z",
    }

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        updates.urllib.request, "urlopen", lambda req, timeout: Resp(json.dumps(payload).encode())
    )
    assert updates.fetch_latest("a/b") == {
        "tag": "v1.2.3",
        "version": "1.2.3",
        "url": payload["html_url"],
        "notes": "notas",
        "published_at": payload["published_at"],
    }


# --------------------------------------------------------------------------- progress
def _event(step, status, minutes_ago=0.0, **extra):
    at = (utcnow() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return json.dumps({"step": step, "status": status, "at": at, **extra})


def _append(data_dir, *lines):
    with (data_dir / updates.PROGRESS_FILE).open("a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")


def _steps(body):
    return {s["id"]: s for s in body["progress"]["steps"]}


def test_progress_follows_the_updater_steps(app_with, github):
    app, client = app_with(install_type="python", updater="systemd-path")
    data_dir = app.state.settings.data_dir
    (data_dir / updates.PROGRESS_FILE).write_text(_event("install", "done") + "\n")  # old run
    assert client.post(f"{API}/settings/update/apply", json={}).status_code == 202

    body = client.get(f"{API}/system/update").json()
    progress = body["progress"]
    assert body["update_in_progress"] is True
    assert progress["version"] == "v99.0.0" and progress["from_version"] == __version__
    assert [s["id"] for s in progress["steps"]] == [s for s, _ in updates.UPDATE_STEPS]
    assert progress["total_steps"] == 7 and progress["current_step"] == 1  # waiting for updater
    assert _steps(body)["request"]["status"] == "done"
    assert _steps(body)["install"]["status"] == "pending"  # the old log was replaced

    # The updater takes the request (removing the file) and starts downloading.
    (data_dir / updates.REQUEST_FILE).unlink()
    _append(
        data_dir,
        _event("start", "done"),
        _event("download", "running", detail="rts.whl: 1,0 de 2,0 MB"),
        "{corrompida",
    )
    body = client.get(f"{API}/system/update").json()
    assert body["update_in_progress"] is True
    assert body["progress"]["current_step"] == 2
    download = _steps(body)["download"]
    assert download["status"] == "running" and download["detail"] == "rts.whl: 1,0 de 2,0 MB"
    assert download["started_at"] and not download["api_offline"]
    assert _steps(body)["stop"]["api_offline"] is True
    assert _steps(body)["start"]["started_at"]  # "done" only: starts where the previous ended

    # Finished: every step done and a result written.
    _append(
        data_dir,
        *(_event(step, "done") for step in ("download", "stop", "backup", "install", "restart")),
    )
    (data_dir / updates.RESULT_FILE).write_text(json.dumps({"ok": True, "version": "v99.0.0"}))
    body = client.get(f"{API}/system/update").json()
    assert body["update_in_progress"] is False
    assert body["progress"]["completed"] is True and body["progress"]["failed"] is False


def test_failed_or_abandoned_progress_is_not_in_progress(app_with, github):
    app, client = app_with(install_type="python", updater="systemd-path")
    data_dir = app.state.settings.data_dir
    _append(
        data_dir,
        _event("request", "done", 40, version="v99.0.0"),
        _event("download", "running", 35),
    )
    body = client.get(f"{API}/system/update").json()
    assert body["update_in_progress"] is False  # no news for more than 30 minutes

    _append(data_dir, _event("download", "failed", detail="sem rede"))
    body = client.get(f"{API}/system/update").json()
    assert body["update_in_progress"] is False
    assert body["progress"]["failed"] is True and body["progress"]["current_step"] == 2
    assert _steps(body)["download"]["detail"] == "sem rede"


def test_duration_of_the_previous_update_is_kept_for_the_estimate(app_with, github):
    app, client = app_with(install_type="python", updater="systemd-path")
    data_dir = app.state.settings.data_dir
    (data_dir / updates.RESULT_FILE).write_text(
        json.dumps(
            {
                "ok": True,
                "requested_at": "2026-11-18T10:00:00+00:00",
                "finished_at": "2026-11-18T10:02:15Z",
            }
        )
    )
    assert client.get(f"{API}/system/update").json()["last_duration_seconds"] is None
    assert client.post(f"{API}/settings/update/apply", json={}).status_code == 202
    assert client.get(f"{API}/system/update").json()["last_duration_seconds"] == 135


def test_no_progress_log_means_no_progress(app_with, github):
    app, client = app_with(install_type="python", updater="systemd-path")
    assert client.get(f"{API}/system/update").json()["progress"] is None

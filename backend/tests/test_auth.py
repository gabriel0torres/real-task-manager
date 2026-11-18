"""Authentication, API tokens, token-triggered runs and workspace cleanup."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from rts.db import Base
from rts.main import create_app
from rts.models import Run, RunTrigger
from tests.conftest import ADMIN_PASSWORD, API, login, make_settings


# --------------------------------------------------------------------------- login
def test_api_requires_login_except_health(anon_client):
    assert anon_client.get(f"{API}/health").status_code == 200
    for path in ("/groups", "/tasks", "/dashboard", "/settings", "/runs", "/auth/me"):
        resp = anon_client.get(f"{API}{path}")
        assert resp.status_code == 401, path
        assert resp.json()["detail"] == "Faça login para continuar."
    assert anon_client.post(f"{API}/groups", json={"name": "x"}).status_code == 401


def test_login_logout_and_me(anon_client):
    resp = login(anon_client)
    assert resp.json()["username"] == "admin" and "manage_config" in resp.json()["permissions"]
    cookie = resp.headers["set-cookie"].lower()
    assert "rts_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie

    assert anon_client.get(f"{API}/auth/me").json()["username"] == "admin"
    assert anon_client.get(f"{API}/groups").status_code == 200
    assert anon_client.post(f"{API}/auth/logout").status_code == 204
    assert anon_client.get(f"{API}/groups").status_code == 401


def test_wrong_credentials_and_throttling(anon_client):
    bad = {"username": "admin", "password": "errada"}
    for _ in range(5):
        resp = anon_client.post(f"{API}/auth/login", json=bad)
        assert resp.status_code == 401 and resp.json()["detail"] == "Usuário ou senha inválidos."
    resp = anon_client.post(f"{API}/auth/login", json=bad)
    assert resp.status_code == 429 and "Muitas tentativas" in resp.json()["detail"]
    # even the right password is refused while blocked
    resp = anon_client.post(
        f"{API}/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert resp.status_code == 429
    # unknown users get the same answer as a wrong password
    resp = anon_client.post(f"{API}/auth/login", json={"username": "ninguem", "password": "x"})
    assert resp.status_code == 401 and resp.json()["detail"] == "Usuário ou senha inválidos."


def test_username_is_case_insensitive(anon_client):
    assert (
        anon_client.post(
            f"{API}/auth/login", json={"username": " ADMIN ", "password": ADMIN_PASSWORD}
        ).status_code
        == 200
    )


def test_change_password_signs_out_other_sessions(app, client):
    other = TestClient(app)
    login(other)
    resp = client.post(
        f"{API}/auth/change-password",
        json={"current_password": "errada", "new_password": "nova-senha-123"},
    )
    assert resp.status_code == 422 and "Senha atual incorreta" in resp.json()["detail"]
    resp = client.post(
        f"{API}/auth/change-password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "curta"},
    )
    assert resp.status_code == 422
    resp = client.post(
        f"{API}/auth/change-password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "nova-senha-123"},
    )
    assert resp.status_code == 200
    assert client.get(f"{API}/auth/me").status_code == 200  # this browser stays in
    assert other.get(f"{API}/auth/me").status_code == 401  # the other one is out
    login(other, password="nova-senha-123")


def test_generated_admin_password_is_logged_and_must_change(tmp_path, caplog):
    settings = make_settings(tmp_path / "gen", admin_password=None)
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with caplog.at_level(logging.WARNING), TestClient(app) as c:
        line = next(r.getMessage() for r in caplog.records if "senha gerada" in r.getMessage())
        password = line.split("senha gerada: ")[1].split()[0]
        assert login(c, password=password).json()["must_change_password"] is True
        c.post(
            f"{API}/auth/change-password",
            json={"current_password": password, "new_password": "minha-senha-123"},
        )
        assert c.get(f"{API}/auth/me").json()["must_change_password"] is False
    # Restarting does not create another admin nor change the password.
    with TestClient(app) as c:
        login(c, password="minha-senha-123")


# --------------------------------------------------------------------------- API tokens
def _token(client, **body) -> dict:
    resp = client.post(f"{API}/auth/tokens", json={"name": "ci", **body})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_api_token_triggers_task(app, client, anon_client, make, db):
    _, _, t = make.tree()
    created = _token(client)
    assert created["token"].startswith("rts_") and created["prefix"] == created["token"][:10]
    assert "token" not in client.get(f"{API}/auth/tokens").json()[0]  # shown only once

    headers = {"Authorization": f"Bearer {created['token']}"}
    resp = anon_client.post(f"{API}/trigger/tasks/{t['id']}", headers=headers)
    assert resp.status_code == 202
    run = db.get(Run, resp.json()["id"])
    assert run.trigger is RunTrigger.API and run.triggered_by == "token:ci"

    by_path = anon_client.post(f"{API}/trigger/FINANCEIRO/fechamento/conciliar", headers=headers)
    assert by_path.status_code == 202
    assert anon_client.post(f"{API}/trigger/x/y/z", headers=headers).status_code == 404
    assert (
        anon_client.post(
            f"{API}/trigger/tasks/{t['id']}", headers={"X-RTS-Token": created["token"]}
        ).status_code
        == 202
    )
    assert client.get(f"{API}/auth/tokens").json()[0]["last_used_at"] is not None


def test_bad_revoked_and_scoped_tokens(client, anon_client, make):
    g, s, t = make.tree()
    other = make.task(s["id"], "outra")
    assert anon_client.post(f"{API}/trigger/tasks/{t['id']}").status_code == 401
    bad = {"Authorization": "Bearer rts_invalido"}
    assert anon_client.post(f"{API}/trigger/tasks/{t['id']}", headers=bad).status_code == 401
    assert anon_client.post(f"{API}/trigger/tasks/999", headers=bad).status_code == 401

    scoped = _token(client, name="só esta", task_id=t["id"])
    headers = {"Authorization": f"Bearer {scoped['token']}"}
    assert scoped["task_name"] == t["name"]
    assert anon_client.post(f"{API}/trigger/tasks/{t['id']}", headers=headers).status_code == 202
    resp = anon_client.post(f"{API}/trigger/tasks/{other['id']}", headers=headers)
    assert resp.status_code == 403

    revoked = client.delete(f"{API}/auth/tokens/{scoped['id']}").json()
    assert revoked["revoked_at"] is not None
    assert anon_client.post(f"{API}/trigger/tasks/{t['id']}", headers=headers).status_code == 401
    # API tokens are not valid for the management API
    assert anon_client.get(f"{API}/groups", headers=headers).status_code == 401


# --------------------------------------------------------------------------- workspaces
def test_deleting_tasks_removes_default_workspaces(client, make, settings):
    g, s, t = make.tree()
    t2 = make.task(s["id"], "segunda")
    for task in (t, t2):
        ws = settings.workspaces_dir / str(task["id"])
        ws.mkdir(parents=True)
        (ws / "arquivo.txt").write_text("x")
    keep = settings.workspaces_dir / "outra-coisa"
    keep.mkdir()

    client.delete(f"{API}/tasks/{t['id']}")
    assert not (settings.workspaces_dir / str(t["id"])).exists()
    assert (settings.workspaces_dir / str(t2["id"])).exists()

    client.delete(f"{API}/groups/{g['id']}")  # cascades to t2
    assert not (settings.workspaces_dir / str(t2["id"])).exists()
    assert keep.exists()

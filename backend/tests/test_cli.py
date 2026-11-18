"""Command line: version and admin password reset."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rts import __version__
from rts.cli import build_parser, main
from rts.config import get_settings
from rts.main import create_app
from tests.conftest import API, make_settings


def test_version(capsys):
    assert main(["version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_parser_commands():
    parser = build_parser()
    assert parser.parse_args(["start", "--port", "9000"]).port == 9000
    assert parser.parse_args(["worker"]).command == "worker"
    with pytest.raises(SystemExit):
        parser.parse_args(["nada"])


@pytest.fixture
def env_settings(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("RTS_DATA_DIR", str(data))
    monkeypatch.setenv("RTS_ADMIN_PASSWORD", "")
    monkeypatch.setenv("RTS_ENV_FILE", str(tmp_path / "missing.env"))
    get_settings.cache_clear()
    yield data
    get_settings.cache_clear()


def test_reset_password_creates_admin_and_forces_change(env_settings, capsys):
    assert main(["admin", "reset-password"]) == 0
    out = capsys.readouterr().out
    password = out.split("redefinida: ")[1].split()[0]
    assert "deverá ser trocada" in out

    app = create_app(make_settings(env_settings, admin_password=None, auto_migrate=True))
    with TestClient(app) as client:
        resp = client.post(f"{API}/auth/login", json={"username": "admin", "password": password})
        assert resp.status_code == 200 and resp.json()["must_change_password"] is True

    # explicit password: no forced change, old sessions dropped
    assert main(["admin", "reset-password", "--password", "escolhida-123"]) == 0
    with TestClient(app) as client:
        resp = client.post(
            f"{API}/auth/login", json={"username": "admin", "password": "escolhida-123"}
        )
        assert resp.status_code == 200 and resp.json()["must_change_password"] is False

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from rts.config import Settings
from rts.db import Base
from rts.main import create_app

API = "/api/v1"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        secret_key=Fernet.generate_key().decode(),
        default_timezone="America/Sao_Paulo",
        auto_migrate=False,
        _env_file=None,
    )


@pytest.fixture
def app(settings):
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(app):
    session = app.state.session_factory()
    yield session
    session.close()


class Factory:
    """Small helper to build hierarchy objects through the API."""

    def __init__(self, client: TestClient) -> None:
        self.c = client

    def _post(self, path: str, payload: dict) -> dict:
        resp = self.c.post(f"{API}{path}", json=payload)
        assert resp.status_code == 201, resp.text
        return resp.json()

    def group(self, name: str = "instagram", **kw) -> dict:
        return self._post("/groups", {"name": name, **kw})

    def subcategory(self, group_id: int, name: str = "postagens", **kw) -> dict:
        return self._post("/subcategories", {"group_id": group_id, "name": name, **kw})

    def task(self, subcategory_id: int, name: str = "publicar", **kw) -> dict:
        payload = {
            "subcategory_id": subcategory_id,
            "name": name,
            "command": "echo ok",
            "cron_expressions": ["0 8 * * *"],
            **kw,
        }
        return self._post("/tasks", payload)

    def variable(self, scope: str, key: str, value: str, owner_id=None, **kw) -> dict:
        return self._post(
            "/variables", {"scope": scope, "owner_id": owner_id, "key": key, "value": value, **kw}
        )

    def tree(self) -> tuple[dict, dict, dict]:
        g = self.group()
        s = self.subcategory(g["id"])
        t = self.task(s["id"])
        return g, s, t


@pytest.fixture
def make(client) -> Factory:
    return Factory(client)

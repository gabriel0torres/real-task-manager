"""Export / import tests, including the round trip export -> clean DB -> identical."""

from __future__ import annotations

import pytest
import yaml
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import rts.transfer.crypto as transfer_crypto
from rts.config import Settings
from rts.db import Base
from rts.main import create_app
from rts.models import Group, Run, RunStatus, RunTrigger, Subcategory, Task, Variable
from rts.services.runs import create_run
from rts.services.settings import get_default_timezone
from tests.conftest import API, Factory

PASSWORD = "senha-forte-123"


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    monkeypatch.setattr(transfer_crypto, "DEFAULT_ITERATIONS", 10_000)


@pytest.fixture
def other_app(tmp_path):
    """A second, clean installation with a different secret key."""
    settings = Settings(
        data_dir=tmp_path / "other",
        secret_key=Fernet.generate_key().decode(),
        default_timezone="UTC",
        auto_migrate=False,
        _env_file=None,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        yield app, client
    app.state.engine.dispose()


def seed(make: Factory) -> dict:
    """Group 'instagram' with 2 subcategories, 3 tasks, variables on every level."""
    c = make.c
    c.patch(f"{API}/settings", json={"default_timezone": "America/Sao_Paulo"})
    make.variable("global", "ENV", "producao", description="ambiente")
    make.variable("global", "API_KEY", "global-secret", is_secret=True)
    g = make.group("instagram", description="Conta principal")
    make.variable("group", "IG_USER", "@empresa", owner_id=g["id"])
    make.variable("group", "IG_TOKEN", "tok-secreto-123", owner_id=g["id"], is_secret=True)
    posts = make.subcategory(g["id"], "postagens", description="Conteúdo")
    reports = make.subcategory(g["id"], "relatórios", is_active=False)
    make.variable("subcategory", "FORMAT", "pdf", owner_id=reports["id"])
    t1 = make.task(
        posts["id"],
        "publicar",
        command="echo 'linha 1'\necho \"linha 2\"\n",
        shell="bash",
        cron_expressions=["30 8 * * 1,3"],
        timezone="UTC",
        timeout_seconds=300,
        max_retries=2,
        retry_interval_seconds=30,
        overlap_policy="queue",
        misfire_policy="run_once",
    )
    make.variable("task", "ENV", "homologacao", owner_id=t1["id"])
    make.task(reports["id"], "mensal", command="python gerar.py", cron_expressions=["0 23 L * *"])
    make.task(
        reports["id"],
        "horaria",
        command="echo ok",
        cron_expressions=["*/15 * * * *"],
        is_active=False,
    )
    return {"group": g, "posts": posts, "reports": reports, "t1": t1}


def export(client, **body) -> tuple[str, dict]:
    resp = client.post(f"{API}/transfer/export", json={"scope": "system", **body})
    assert resp.status_code == 200, resp.text
    return resp.text, resp.headers


def preview(client, content, **opts):
    resp = client.post(f"{API}/transfer/import/preview", json={"content": content, **opts})
    assert resp.status_code == 200, resp.text
    return resp.json()


def apply(client, content, expect=200, **opts):
    resp = client.post(f"{API}/transfer/import/apply", json={"content": content, **opts})
    assert resp.status_code == expect, resp.text
    return resp.json()


def snapshot(app) -> dict:
    """Normalised view of the whole configuration (secrets decrypted)."""
    box = app.state.secret_box
    with app.state.session_factory() as s:

        def variables(**owner):
            stmt = select(Variable)
            for column, value in owner.items():
                stmt = stmt.where(getattr(Variable, column) == value)
            out = {}
            for v in s.scalars(stmt):
                value = box.decrypt(v.value) if v.is_secret and v.value else v.value
                out[v.key] = (value, v.is_secret, v.description)
            return out

        data = {
            "default_tz": get_default_timezone(s, "UTC"),
            "globals": variables(scope="global"),
            "groups": {},
        }
        for g in s.scalars(select(Group)):
            gd = {"desc": g.description, "active": g.is_active, "vars": variables(group_id=g.id),
                  "subs": {}}  # fmt: skip
            for sub in g.subcategories:
                sd = {"desc": sub.description, "active": sub.is_active,
                      "vars": variables(subcategory_id=sub.id), "tasks": {}}  # fmt: skip
                for t in sub.tasks:
                    sd["tasks"][t.name] = {
                        "fields": (
                            t.description,
                            t.command,
                            t.shell,
                            t.working_dir,
                            tuple(t.cron_expressions),
                            t.timezone,
                            t.timeout_seconds,
                            t.max_retries,
                            t.retry_interval_seconds,
                            t.overlap_policy,
                            t.misfire_policy,
                            t.is_active,
                        ),  # fmt: skip
                        "vars": variables(task_id=t.id),
                    }
                gd["subs"][sub.name] = sd
            data["groups"][g.name] = gd
        return data


def count(app, model) -> int:
    with app.state.session_factory() as s:
        return s.scalar(select(func.count()).select_from(model))


# =========================================================================== export
def test_export_system_omitting_secrets(client, make, db):
    ids = seed(make)
    run = create_run(db, ids["t1"]["id"], RunTrigger.MANUAL)
    run.status = RunStatus.SUCCESS
    db.commit()

    content, headers = export(client)
    assert headers["content-disposition"].startswith('attachment; filename="rts-system-sistema-')
    assert headers["x-rts-secrets"] == "2"
    assert content.startswith("# Real Task Scheduler - exportação (sistema inteiro)")

    doc = yaml.safe_load(content)
    assert doc["schema_version"] == 1 and doc["scope"] == "system"
    assert doc["secrets_mode"] == "omit" and "encryption" not in doc
    assert doc["settings"] == {"default_timezone": "America/Sao_Paulo"}
    assert {"key": "API_KEY", "secret": True, "value": None} in doc["variables"]
    assert "global-secret" not in content and "tok-secreto-123" not in content

    task = doc["groups"][0]["subcategories"][0]["tasks"][0]
    assert task["schedule"] == {
        "cron": ["30 8 * * 1,3"],
        "timezone": "UTC",
        "description": "Toda segunda e quarta às 08:30",
    }
    assert task["retries"] == {"max": 2, "interval_seconds": 30}
    assert "command: |" in content  # multi-line commands are readable blocks
    assert "runs" not in content and "last_fire_at" not in content  # no history


def test_export_encrypted_requires_password_and_hides_values(client, make):
    seed(make)
    resp = client.post(
        f"{API}/transfer/export", json={"scope": "system", "secrets_mode": "encrypted"}
    )
    assert resp.status_code == 422
    resp = client.post(
        f"{API}/transfer/export",
        json={"scope": "system", "secrets_mode": "encrypted", "password": "curta"},
    )
    assert resp.status_code == 422 and "8 caracteres" in resp.text

    content, _ = export(client, secrets_mode="encrypted", password=PASSWORD)
    doc = yaml.safe_load(content)
    assert doc["encryption"]["algorithm"] == "fernet-pbkdf2-sha256"
    assert "tok-secreto-123" not in content
    token = next(v for v in doc["groups"][0]["variables"] if v["key"] == "IG_TOKEN")
    assert token["secret"] is True and token["value_encrypted"].startswith("gAAAA")


def test_export_group_and_subcategory_scopes(client, make):
    ids = seed(make)
    content, headers = export(client, scope="group", id=ids["group"]["id"])
    doc = yaml.safe_load(content)
    assert "rts-group-instagram-" in headers["content-disposition"]
    assert doc["scope"] == "group" and "variables" not in doc and "settings" not in doc
    assert [s["name"] for s in doc["groups"][0]["subcategories"]] == ["postagens", "relatórios"]

    content, headers = export(client, scope="subcategory", id=ids["reports"]["id"])
    doc = yaml.safe_load(content)
    assert "rts-subcategory-instagram-relatorios-" in headers["content-disposition"]
    group = doc["groups"][0]
    assert group["name"] == "instagram" and group["variables"] == []
    assert [s["name"] for s in group["subcategories"]] == ["relatórios"]

    assert client.post(f"{API}/transfer/export", json={"scope": "group"}).status_code == 422
    assert (
        client.post(f"{API}/transfer/export", json={"scope": "group", "id": 999}).status_code == 404
    )


# =========================================================================== round trip
def test_round_trip_encrypted_into_clean_database_is_identical(app, client, make, other_app):
    seed(make)
    content, _ = export(client, secrets_mode="encrypted", password=PASSWORD)
    target, target_client = other_app

    plan = preview(target_client, content)
    assert plan["valid"] and plan["needs_password"] and plan["password_ok"] is None

    report = apply(target_client, content, password=PASSWORD, activate_tasks=True)
    assert report["applied"] and report["pending_secrets"] == []
    assert report["summary"]["create"] == 6  # group + 2 subs + 3 tasks
    assert snapshot(target) == snapshot(app)

    # Exporting again from the clean install gives the same document.
    again, _ = export(target_client)
    first, second = yaml.safe_load(export(client)[0]), yaml.safe_load(again)
    first.pop("exported_at"), second.pop("exported_at")
    assert first == second


def test_round_trip_omitting_secrets_lists_pending_and_accepts_values(app, client, make, other_app):
    seed(make)
    content, _ = export(client)
    target, target_client = other_app

    plan = preview(target_client, content)
    assert plan["needs_password"] is False
    assert {p["path"] for p in plan["pending_secrets"]} == {
        "globals/var:API_KEY",
        "group:instagram/var:IG_TOKEN",
    }

    report = apply(
        target_client,
        content,
        activate_tasks=True,
        secret_values={"globals/var:API_KEY": "global-secret"},
    )
    assert [p["key"] for p in report["pending_secrets"]] == ["IG_TOKEN"]
    snap = snapshot(target)
    assert snap["globals"]["API_KEY"] == ("global-secret", True, "")
    assert snap["groups"]["instagram"]["vars"]["IG_TOKEN"] == (None, True, "")  # a preencher
    expected = snapshot(app)
    expected["groups"]["instagram"]["vars"]["IG_TOKEN"] = (None, True, "")
    assert snap == expected


def test_imported_tasks_are_paused_by_default(client, make, other_app):
    seed(make)
    content, _ = export(client)
    target, target_client = other_app
    report = apply(target_client, content)
    assert report["tasks_paused"] is True
    assert any("entra pausada" in d for i in report["items"] for d in i["details"])
    with target.state.session_factory() as s:
        assert not any(t.is_active for t in s.scalars(select(Task)))
        # groups/subcategories keep the state from the file
        assert (
            s.scalar(select(Subcategory.is_active).where(Subcategory.name == "relatórios")) is False
        )


# =========================================================================== validation
@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("a: [unclosed", "YAML inválido (linha"),
        ("- just\n- a list\n", "não é uma exportação do RTS"),
        ("foo: 1\n", "schema_version"),
        ("schema_version: 2\n", "suporta até 1"),
    ],
)
def test_invalid_files_are_rejected_before_any_change(client, content, message):
    report = preview(client, content)
    assert report["valid"] is False and message in report["errors"][0]
    resp = client.post(f"{API}/transfer/import/apply", json={"content": content})
    assert resp.status_code == 422


def test_schema_errors_point_to_the_location(app, client, make):
    seed(make)
    content, _ = export(client)
    doc = yaml.safe_load(content)
    task = doc["groups"][0]["subcategories"][1]["tasks"][0]
    task["schedule"]["cron"] = ["61 * * * *"]
    doc["groups"][0]["subcategories"][0]["unknown_field"] = 1
    before = snapshot(app)

    report = preview(client, yaml.safe_dump(doc, allow_unicode=True))
    assert report["valid"] is False
    joined = "\n".join(report["errors"])
    assert (
        "groups[instagram].subcategories[relatórios].tasks[horaria].schedule.cron: "
        "'61 * * * *': Valor 61 fora do intervalo 0-59 no campo minuto." in joined
    )
    assert "groups[instagram].subcategories[postagens].unknown_field: campo desconhecido" in joined

    dup = yaml.safe_load(content)
    dup["groups"][0]["subcategories"][0]["tasks"].append({"name": "PUBLICAR", "command": "x"})
    report = preview(client, yaml.safe_dump(dup, allow_unicode=True))
    assert "tarefa 'PUBLICAR' aparece mais de uma vez" in report["errors"][0]
    assert snapshot(app) == before


def test_wrong_or_missing_password(client, make, other_app):
    seed(make)
    content, _ = export(client, secrets_mode="encrypted", password=PASSWORD)
    target, target_client = other_app
    report = preview(target_client, content, password="outra-senha-999")
    assert report["valid"] is False and report["password_ok"] is False
    assert report["errors"] == ["Senha incorreta."]
    report = apply(target_client, content, expect=422)
    assert "Informe a senha" in report["errors"][0]
    assert count(target, Group) == 0


def test_preview_does_not_change_anything(client, make, other_app):
    seed(make)
    content, _ = export(client)
    target, target_client = other_app
    plan = preview(target_client, content, activate_tasks=True)
    assert plan["valid"] and plan["applied"] is False
    assert [i["action"] for i in plan["items"]].count("create") == 6
    assert count(target, Group) == 0 and count(target, Variable) == 0
    assert snapshot(target)["default_tz"] == "UTC"


# =========================================================================== conflicts
def _changed_file(client, ids) -> str:
    """Export of the group, then edited: task command changed, sub 'novos' added."""
    content, _ = export(client, scope="group", id=ids["group"]["id"])
    doc = yaml.safe_load(content)
    group = doc["groups"][0]
    group["description"] = "Descrição nova"
    group["variables"] = [{"key": "IG_USER", "value": "@nova"}, {"key": "NEW", "value": "1"}]
    posts = group["subcategories"][0]
    posts["tasks"][0]["command"] = "echo novo"
    posts["tasks"].append({"name": "nova-tarefa", "command": "echo 1"})
    group["subcategories"] = [posts, {"name": "novos", "tasks": []}]  # drops 'relatórios'
    return yaml.safe_dump(doc, allow_unicode=True)


def test_conflict_defaults_to_skip(app, client, make):
    ids = seed(make)
    content = _changed_file(client, ids)
    before = snapshot(app)
    plan = preview(client, content)
    group_item = plan["items"][0]
    assert group_item["path"] == "group:instagram" and group_item["conflict"] is True
    assert group_item["action"] == "skip"
    assert group_item["allowed_resolutions"] == ["overwrite", "merge", "rename", "skip"]
    apply(client, content)
    assert snapshot(app) == before


def test_overwrite_makes_group_identical_to_file(app, client, make, db):
    ids = seed(make)
    run = create_run(db, ids["t1"]["id"], RunTrigger.MANUAL)
    db.commit()
    content = _changed_file(client, ids)
    res = {"group:instagram": {"action": "overwrite"}}

    plan = preview(client, content, resolutions=res, activate_tasks=True)
    actions = {i["path"]: i["action"] for i in plan["items"]}
    assert actions["group:instagram"] == "update"
    assert actions["group:instagram/sub:relatórios"] == "delete"
    assert actions["group:instagram/sub:novos"] == "create"
    assert actions["group:instagram/sub:postagens/task:publicar"] == "update"
    assert actions["group:instagram/sub:postagens/task:nova-tarefa"] == "create"

    apply(client, content, resolutions=res, activate_tasks=True)
    group = snapshot(app)["groups"]["instagram"]
    assert group["desc"] == "Descrição nova"
    assert group["vars"] == {"IG_USER": ("@nova", False, ""), "NEW": ("1", False, "")}  # exact
    assert set(group["subs"]) == {"postagens", "novos"}
    assert group["subs"]["postagens"]["tasks"]["publicar"]["fields"][1] == "echo novo"
    # Updated in place: the task keeps its id and its history.
    db.expire_all()
    assert db.get(Run, run.id) is not None and db.get(Task, ids["t1"]["id"]).command == "echo novo"


def test_merge_keeps_existing_and_resolves_children(app, client, make):
    ids = seed(make)
    content = _changed_file(client, ids)
    res = {
        "group:instagram": {"action": "merge"},
        "group:instagram/sub:postagens": {"action": "merge"},
        "group:instagram/sub:postagens/task:publicar": {
            "action": "rename",
            "new_name": "publicar-v2",
        },
    }
    plan = preview(client, content, resolutions=res)
    conflicts = {i["path"]: i["resolution"] for i in plan["items"] if i["conflict"]}
    assert conflicts == {
        "group:instagram": "merge",
        "group:instagram/sub:postagens": "merge",
        "group:instagram/sub:postagens/task:publicar": "rename",
    }

    apply(client, content, resolutions=res)
    group = snapshot(app)["groups"]["instagram"]
    assert set(group["subs"]) == {"postagens", "relatórios", "novos"}  # nothing deleted
    assert group["vars"]["IG_USER"] == ("@nova", False, "")  # file wins
    assert group["vars"]["IG_TOKEN"] == ("tok-secreto-123", True, "")  # kept
    tasks = group["subs"]["postagens"]["tasks"]
    assert set(tasks) == {"publicar", "publicar-v2", "nova-tarefa"}
    assert tasks["publicar"]["fields"][1] != "echo novo"  # original untouched
    assert tasks["publicar-v2"]["fields"][1] == "echo novo"


def test_rename_group_auto_name_and_collision(app, client, make):
    ids = seed(make)
    content, _ = export(client, scope="group", id=ids["group"]["id"])
    apply(client, content, resolutions={"group:instagram": {"action": "rename"}})
    apply(client, content, resolutions={"group:instagram": {"action": "rename"}})
    assert set(snapshot(app)["groups"]) == {
        "instagram", "instagram (importado)", "instagram (importado 2)",
    }  # fmt: skip

    report = apply(
        client,
        content,
        expect=422,
        resolutions={"group:instagram": {"action": "rename", "new_name": "INSTAGRAM (importado)"}},
    )
    assert "Já existe" in report["errors"][0]


def test_import_is_atomic(app, client, make, other_app):
    """A failure in the second group leaves nothing from the first one behind."""
    seed(make)
    make.group("outro")
    content, _ = export(client)
    target, target_client = other_app
    target_client.post(f"{API}/groups", json={"name": "outro"})
    target_client.post(f"{API}/groups", json={"name": "existente"})
    before = count(target, Group), count(target, Task), count(target, Variable)

    report = apply(
        target_client,
        content,
        expect=422,
        resolutions={"group:outro": {"action": "rename", "new_name": "existente"}},
    )
    assert report["applied"] is False
    assert (count(target, Group), count(target, Task), count(target, Variable)) == before


def test_secret_without_value_keeps_existing_value_on_merge(app, client, make):
    ids = seed(make)
    content, _ = export(client, scope="group", id=ids["group"]["id"])  # omit mode
    plan = preview(client, content, resolutions={"group:instagram": {"action": "overwrite"}})
    group_item = plan["items"][0]
    assert any("mantêm o valor atual: IG_TOKEN" in d for d in group_item["details"])
    assert plan["pending_secrets"] == []
    apply(client, content, resolutions={"group:instagram": {"action": "overwrite"}})
    assert snapshot(app)["groups"]["instagram"]["vars"]["IG_TOKEN"] == ("tok-secreto-123", True, "")


def test_global_variables_conflict(app, client, make, other_app):
    seed(make)
    content, _ = export(client)
    target, target_client = other_app
    target_client.post(f"{API}/variables", json={"scope": "global", "key": "ENV", "value": "dev"})
    target_client.post(f"{API}/variables", json={"scope": "global", "key": "LOCAL", "value": "x"})

    plan = preview(target_client, content)
    globals_item = next(i for i in plan["items"] if i["path"] == "globals")
    assert globals_item["conflict"] and globals_item["action"] == "skip"
    assert globals_item["allowed_resolutions"] == ["overwrite", "merge", "skip"]

    apply(target_client, content, resolutions={"globals": {"action": "merge"}})
    g = snapshot(target)["globals"]
    assert g["ENV"] == ("producao", False, "ambiente") and "LOCAL" in g

    apply(target_client, content, resolutions={"globals": {"action": "overwrite"}})
    assert "LOCAL" not in snapshot(target)["globals"]


def test_settings_can_be_left_out(client, make, other_app):
    seed(make)
    content, _ = export(client)
    target, target_client = other_app
    report = apply(target_client, content, apply_settings=False)
    settings_item = next(i for i in report["items"] if i["kind"] == "settings")
    assert settings_item["action"] == "skip"
    assert snapshot(target)["default_tz"] == "UTC"


def test_subcategory_import_into_target_or_new_group(app, client, make, other_app):
    ids = seed(make)
    content, _ = export(client, scope="subcategory", id=ids["reports"]["id"])
    target, target_client = other_app

    report = apply(target_client, content)
    assert [i["action"] for i in report["items"][:2]] == ["create", "create"]
    assert set(snapshot(target)["groups"]) == {"instagram"}

    other = target_client.post(f"{API}/groups", json={"name": "relatorios-gerais"}).json()
    apply(target_client, content, target_group_id=other["id"])
    subs = snapshot(target)["groups"]["relatorios-gerais"]["subs"]
    assert set(subs) == {"relatórios"} and set(subs["relatórios"]["tasks"]) == {"mensal", "horaria"}
    assert snapshot(target)["groups"]["relatorios-gerais"]["vars"] == {}

    report = apply(target_client, content, expect=422, target_group_id=999)
    assert "não encontrado" in report["errors"][0]

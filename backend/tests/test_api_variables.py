from sqlalchemy import select

from rts.models import Variable
from rts.services.hierarchy import get_task
from rts.services.variables import build_task_environment
from tests.conftest import API


def test_create_variables_at_every_scope(client, make):
    g, s, t = make.tree()
    make.variable("global", "A", "g")
    make.variable("group", "A", "gr", owner_id=g["id"])
    make.variable("subcategory", "A", "sub", owner_id=s["id"])
    make.variable("task", "A", "task", owner_id=t["id"])
    assert len(client.get(f"{API}/variables").json()) == 4
    only_group = client.get(f"{API}/variables", params={"scope": "group", "owner_id": g["id"]})
    assert [(v["key"], v["value"], v["owner_id"]) for v in only_group.json()] == [
        ("A", "gr", g["id"])
    ]


def test_owner_validation(client, make):
    g = make.group()
    post = lambda **p: client.post(f"{API}/variables", json={"key": "K", "value": "v", **p})  # noqa: E731
    assert post(scope="global", owner_id=g["id"]).status_code == 422
    assert post(scope="group").status_code == 422
    assert post(scope="group", owner_id=999).status_code == 404
    assert post(scope="task", owner_id=999).status_code == 404


def test_key_validation(client):
    for key in ["1ABC", "A-B", "A B", "", "RTS_FOO", "rts_foo"]:
        resp = client.post(f"{API}/variables", json={"scope": "global", "key": key, "value": "v"})
        assert resp.status_code == 422, key


def test_duplicate_key_same_level_conflicts_but_other_levels_ok(client, make):
    g1, g2 = make.group("g1"), make.group("g2")
    make.variable("group", "K", "1", owner_id=g1["id"])
    make.variable("group", "K", "1", owner_id=g2["id"])
    make.variable("global", "K", "1")
    resp = client.post(
        f"{API}/variables", json={"scope": "group", "owner_id": g1["id"], "key": "K", "value": "2"}
    )
    assert resp.status_code == 409


def test_secret_is_encrypted_and_never_returned(client, make, db):
    v = make.variable("global", "TOKEN", "super-secret", is_secret=True)
    assert v["value"] is None and v["has_value"] is True and v["is_secret"] is True
    assert client.get(f"{API}/variables/{v['id']}").json()["value"] is None
    assert "super-secret" not in client.get(f"{API}/variables").text

    stored = db.scalar(select(Variable.value).where(Variable.id == v["id"]))
    assert stored != "super-secret" and stored.startswith("gAAAA")


def test_secret_update_rules(client, make, app, db):
    v = make.variable("global", "TOKEN", "old", is_secret=True)
    box = app.state.secret_box
    url = f"{API}/variables/{v['id']}"

    def stored():
        db.expire_all()
        return db.get(Variable, v["id"])

    # omitting value keeps the secret
    assert client.patch(url, json={"description": "api"}).status_code == 200
    assert box.decrypt(stored().value) == "old"

    # replace
    client.patch(url, json={"value": "new"})
    assert box.decrypt(stored().value) == "new"

    # un-secreting requires a new value
    resp = client.patch(url, json={"is_secret": False})
    assert resp.status_code == 422 and "novo valor" in resp.json()["detail"]
    body = client.patch(url, json={"is_secret": False, "value": "plain"}).json()
    assert body["value"] == "plain" and stored().value == "plain"

    # secreting an existing plain value encrypts it in place
    body = client.patch(url, json={"is_secret": True}).json()
    assert body["value"] is None
    assert box.decrypt(stored().value) == "plain"


def test_rename_key_conflict(client, make):
    make.variable("global", "A", "1")
    b = make.variable("global", "B", "2")
    assert client.patch(f"{API}/variables/{b['id']}", json={"key": "A"}).status_code == 409


def test_effective_variables_inheritance(client, make):
    g, s, t = make.tree()
    make.variable("global", "ENV", "prod")
    make.variable("global", "ONLY_GLOBAL", "1")
    make.variable("group", "ENV", "group-env", owner_id=g["id"])
    make.variable("subcategory", "ENV", "sub-env", owner_id=s["id"])
    make.variable("subcategory", "API_KEY", "k", owner_id=s["id"], is_secret=True)
    make.variable("task", "ONLY_TASK", "t", owner_id=t["id"])

    # unrelated group must not leak
    other = make.group("other")
    make.variable("group", "LEAK", "x", owner_id=other["id"])

    eff = {v["key"]: v for v in client.get(f"{API}/tasks/{t['id']}/effective-variables").json()}
    assert sorted(eff) == ["API_KEY", "ENV", "ONLY_GLOBAL", "ONLY_TASK"]

    env = eff["ENV"]
    assert env["value"] == "sub-env"
    assert env["source"]["scope"] == "subcategory" and env["source"]["owner_name"] == s["name"]
    assert [o["scope"] for o in env["overrides"]] == ["group", "global"]

    assert eff["ONLY_GLOBAL"]["source"]["scope"] == "global"
    assert eff["ONLY_TASK"]["source"]["owner_id"] == t["id"]
    assert eff["API_KEY"]["value"] is None and eff["API_KEY"]["is_secret"] is True


def test_subcategory_inherited_variables_for_new_tasks(client, make):
    g, s, t = make.tree()
    make.variable("global", "ENV", "prod")
    make.variable("group", "ENV", "grupo", owner_id=g["id"])
    make.variable("subcategory", "DIR", "/x", owner_id=s["id"])
    make.variable("task", "ONLY_TASK", "1", owner_id=t["id"])  # not inherited by new tasks
    eff = client.get(f"{API}/subcategories/{s['id']}/effective-variables").json()
    assert [(v["key"], v["value"], v["source"]["scope"]) for v in eff] == [
        ("DIR", "/x", "subcategory"),
        ("ENV", "grupo", "group"),
    ]
    assert eff[1]["overrides"][0]["scope"] == "global"
    assert client.get(f"{API}/subcategories/999/effective-variables").status_code == 404


def test_task_level_overrides_everything(client, make):
    g, s, t = make.tree()
    make.variable("global", "X", "1")
    make.variable("task", "X", "4", owner_id=t["id"])
    eff = client.get(f"{API}/tasks/{t['id']}/effective-variables").json()
    assert eff[0]["value"] == "4" and eff[0]["source"]["scope"] == "task"


def test_build_task_environment_decrypts_and_reports_missing(make, app, db):
    g, _, t = make.tree()
    make.variable("global", "PLAIN", "v")
    make.variable("group", "SECRET", "s3cr3t", owner_id=g["id"], is_secret=True)
    # simulate an imported secret without value
    db.add(Variable(scope="task", task_id=t["id"], key="PENDING", value=None, is_secret=True))
    db.commit()

    result = build_task_environment(db, app.state.secret_box, get_task(db, t["id"]))
    assert result.env == {"PLAIN": "v", "SECRET": "s3cr3t"}
    assert result.secret_values == ["s3cr3t"]
    assert result.missing_keys == ["PENDING"]


def test_deleting_task_removes_its_variables(client, make):
    _, _, t = make.tree()
    make.variable("global", "G", "1")
    make.variable("task", "T", "1", owner_id=t["id"])
    client.delete(f"{API}/tasks/{t['id']}")
    assert [v["key"] for v in client.get(f"{API}/variables").json()] == ["G"]


def test_new_task_can_copy_the_variables_of_another(client, make, app, db):
    g, s, source = make.tree()
    other = make.subcategory(g["id"], "outra")
    make.variable("task", "EMPRESA", "nacional", owner_id=source["id"], description="filial")
    make.variable("task", "SENHA", "s3gredo", owner_id=source["id"], is_secret=True)

    copy = make.task(other["id"], "copia", copy_variables_from=source["id"])
    own = {
        v["key"]: v
        for v in client.get(
            f"{API}/variables", params={"scope": "task", "owner_id": copy["id"]}
        ).json()
    }
    assert set(own) == {"EMPRESA", "SENHA"}
    assert own["EMPRESA"]["value"] == "nacional" and own["EMPRESA"]["description"] == "filial"
    assert own["SENHA"]["is_secret"] and own["SENHA"]["has_value"]
    # The copied secret decrypts to the same value when the task runs.
    resolved = build_task_environment(db, app.state.secret_box, get_task(db, copy["id"]))
    assert resolved.env["SENHA"] == "s3gredo" and resolved.env["EMPRESA"] == "nacional"
    # The source keeps its variables.
    src = client.get(f"{API}/variables", params={"scope": "task", "owner_id": source["id"]})
    assert len(src.json()) == 2

    bad = client.post(
        f"{API}/tasks",
        json={
            "subcategory_id": s["id"],
            "name": "x",
            "command": "echo",
            "copy_variables_from": 999,
        },
    )
    assert bad.status_code == 422 and "999" in bad.json()["detail"]

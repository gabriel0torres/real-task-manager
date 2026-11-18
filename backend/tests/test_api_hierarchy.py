from tests.conftest import API


# --------------------------------------------------------------------------- groups
def test_group_crud(client, make):
    g = make.group("financeiro", description="Rotinas financeiras")
    assert g["is_active"] is True and g["description"] == "Rotinas financeiras"

    resp = client.patch(f"{API}/groups/{g['id']}", json={"is_active": False, "name": "Insta"})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False and resp.json()["name"] == "Insta"

    assert [x["name"] for x in client.get(f"{API}/groups").json()] == ["Insta"]
    assert client.delete(f"{API}/groups/{g['id']}").status_code == 204
    assert client.get(f"{API}/groups/{g['id']}").status_code == 404


def test_group_name_is_unique_case_insensitive(client, make):
    make.group("Financeiro")
    resp = client.post(f"{API}/groups", json={"name": "  financeiro "})
    assert resp.status_code == 409
    assert "Já existe um grupo" in resp.json()["detail"]


def test_group_rename_conflict(client, make):
    make.group("a")
    b = make.group("b")
    assert client.patch(f"{API}/groups/{b['id']}", json={"name": "A"}).status_code == 409
    # renaming to itself (different case) is fine
    assert client.patch(f"{API}/groups/{b['id']}", json={"name": "B"}).status_code == 200


def test_group_validation(client):
    assert client.post(f"{API}/groups", json={"name": "   "}).status_code == 422
    assert client.post(f"{API}/groups", json={"name": "x" * 101}).status_code == 422


def test_null_on_required_field_is_rejected(client, make):
    g = make.group()
    resp = client.patch(f"{API}/groups/{g['id']}", json={"name": None})
    assert resp.status_code == 422


def test_delete_group_cascades(client, make):
    g, s, t = make.tree()
    make.variable("task", "X", "1", owner_id=t["id"])
    assert client.delete(f"{API}/groups/{g['id']}").status_code == 204
    assert client.get(f"{API}/subcategories/{s['id']}").status_code == 404
    assert client.get(f"{API}/tasks/{t['id']}").status_code == 404
    assert client.get(f"{API}/variables").json() == []


# --------------------------------------------------------------------------- subcategories
def test_subcategory_crud_and_filters(client, make):
    g1, g2 = make.group("g1"), make.group("g2")
    s1 = make.subcategory(g1["id"], "fechamento")
    make.subcategory(g2["id"], "fechamento")  # same name in another group is fine

    assert len(client.get(f"{API}/subcategories").json()) == 2
    only_g1 = client.get(f"{API}/subcategories", params={"group_id": g1["id"]}).json()
    assert [s["id"] for s in only_g1] == [s1["id"]]

    resp = client.post(f"{API}/subcategories", json={"group_id": g1["id"], "name": "FECHAMENTO"})
    assert resp.status_code == 409


def test_subcategory_requires_existing_group(client):
    resp = client.post(f"{API}/subcategories", json={"group_id": 999, "name": "x"})
    assert resp.status_code == 404
    assert "Grupo 999" in resp.json()["detail"]


def test_move_subcategory_checks_target_names(client, make):
    g1, g2 = make.group("g1"), make.group("g2")
    s1 = make.subcategory(g1["id"], "rel")
    make.subcategory(g2["id"], "rel")
    resp = client.patch(f"{API}/subcategories/{s1['id']}", json={"group_id": g2["id"]})
    assert resp.status_code == 409
    resp = client.patch(
        f"{API}/subcategories/{s1['id']}", json={"group_id": g2["id"], "name": "rel2"}
    )
    assert resp.status_code == 200 and resp.json()["group_id"] == g2["id"]


def test_paused_group_pauses_subcategory_effectively(client, make):
    g = make.group()
    s = make.subcategory(g["id"])
    client.patch(f"{API}/groups/{g['id']}", json={"is_active": False})
    body = client.get(f"{API}/subcategories/{s['id']}").json()
    assert body["is_active"] is True and body["is_effectively_active"] is False


# --------------------------------------------------------------------------- tasks
def test_task_create_defaults_and_derived_fields(client, make):
    g, s, _ = make.tree()
    t = make.task(s["id"], "relatorio", cron_expressions=["  30 8  * * MON ", "0 0 L * *"])
    assert t["cron_expressions"] == ["30 8 * * mon", "0 0 L * *"]
    assert t["group_id"] == g["id"]
    assert t["timezone"] is None and t["effective_timezone"] == "America/Sao_Paulo"
    assert t["overlap_policy"] == "skip" and t["misfire_policy"] == "ignore"
    assert t["max_retries"] == 0 and t["retry_interval_seconds"] == 60
    assert t["is_effectively_active"] is True
    assert t["next_run_at"] is not None


def test_task_without_schedule_is_allowed(make):
    _, s, _ = make.tree()
    t = make.task(s["id"], "manual-only", cron_expressions=[])
    assert t["cron_expressions"] == [] and t["next_run_at"] is None


def test_task_invalid_cron_returns_clear_error(client, make):
    _, s, _ = make.tree()
    resp = client.post(
        f"{API}/tasks",
        json={
            "subcategory_id": s["id"],
            "name": "x",
            "command": "echo",
            "cron_expressions": ["61 * * * *"],
        },
    )
    assert resp.status_code == 422
    assert "fora do intervalo 0-59 no campo minuto" in resp.text


def test_task_invalid_timezone_and_fields(client, make):
    _, s, _ = make.tree()
    base = {"subcategory_id": s["id"], "name": "x", "command": "echo"}
    assert client.post(f"{API}/tasks", json={**base, "timezone": "Nope/Zone"}).status_code == 422
    assert client.post(f"{API}/tasks", json={**base, "timeout_seconds": 0}).status_code == 422
    assert client.post(f"{API}/tasks", json={**base, "max_retries": -1}).status_code == 422
    assert client.post(f"{API}/tasks", json={**base, "overlap_policy": "x"}).status_code == 422
    assert client.post(f"{API}/tasks", json={**base, "command": "   "}).status_code == 422


def test_task_name_unique_within_subcategory(client, make):
    _, s, t = make.tree()
    resp = client.post(
        f"{API}/tasks", json={"subcategory_id": s["id"], "name": t["name"].upper(), "command": "x"}
    )
    assert resp.status_code == 409


def test_task_update_and_clear_nullable_fields(client, make):
    _, _, t = make.tree()
    resp = client.patch(
        f"{API}/tasks/{t['id']}",
        json={"timezone": "UTC", "timeout_seconds": 30, "overlap_policy": "queue", "shell": "bash"},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["effective_timezone"] == "UTC" and body["timeout_seconds"] == 30
    assert body["overlap_policy"] == "queue" and body["shell"] == "bash"

    body = client.patch(
        f"{API}/tasks/{t['id']}", json={"timezone": None, "timeout_seconds": None}
    ).json()
    assert body["timezone"] is None and body["effective_timezone"] == "America/Sao_Paulo"
    assert body["timeout_seconds"] is None

    assert client.patch(f"{API}/tasks/{t['id']}", json={"command": None}).status_code == 422


def test_task_effectively_paused_by_parents(client, make):
    g, s, t = make.tree()
    client.patch(f"{API}/subcategories/{s['id']}", json={"is_active": False})
    body = client.get(f"{API}/tasks/{t['id']}").json()
    assert body["is_active"] is True
    assert body["is_effectively_active"] is False and body["next_run_at"] is None

    client.patch(f"{API}/subcategories/{s['id']}", json={"is_active": True})
    client.patch(f"{API}/groups/{g['id']}", json={"is_active": False})
    assert client.get(f"{API}/tasks/{t['id']}").json()["is_effectively_active"] is False


def test_task_list_filters(client, make):
    g1 = make.group("g1")
    s1 = make.subcategory(g1["id"], "a")
    s2 = make.subcategory(g1["id"], "b")
    g2 = make.group("g2")
    s3 = make.subcategory(g2["id"], "c")
    make.task(s1["id"], "t1")
    make.task(s2["id"], "t2")
    make.task(s3["id"], "t3")
    names = lambda **p: [t["name"] for t in client.get(f"{API}/tasks", params=p).json()]  # noqa: E731
    assert names() == ["t1", "t2", "t3"]
    assert names(group_id=g1["id"]) == ["t1", "t2"]
    assert names(subcategory_id=s3["id"]) == ["t3"]


def test_default_timezone_setting_changes_effective_timezone(client, make):
    _, _, t = make.tree()
    assert client.get(f"{API}/settings").json()["default_timezone"] == "America/Sao_Paulo"
    assert client.patch(f"{API}/settings", json={"default_timezone": "Bad/Zone"}).status_code == 422
    client.patch(f"{API}/settings", json={"default_timezone": "Europe/Lisbon"})
    assert client.get(f"{API}/tasks/{t['id']}").json()["effective_timezone"] == "Europe/Lisbon"


def test_changes_bump_config_revision(client, make, db):
    from rts.services.settings import CONFIG_REVISION, get_setting

    make.tree()
    rev = get_setting(db, CONFIG_REVISION)
    assert rev == 3  # group + subcategory + task

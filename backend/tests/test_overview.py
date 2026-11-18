from datetime import UTC, datetime

import pytest

from rts.models import RunStatus, RunTrigger
from rts.scheduling.cron import CronError
from rts.scheduling.describe import describe
from rts.services.runs import create_run
from tests.conftest import API


@pytest.mark.parametrize(
    ("expressions", "expected"),
    [
        (["30 8 * * 1,3"], "Toda segunda e quarta às 08:30"),
        (["0 8 * * *", "30 17 * * *"], "Todos os dias às 08:00 e 17:30"),
        (["0 8,12,18 * * *"], "Todos os dias às 08:00, 12:00 e 18:00"),
        (["*/15 * * * *"], "A cada 15 minutos"),
        (["*/15 * * * 1-5"], "A cada 15 minutos, de segunda a sexta"),
        (["0 */2 * * *"], "A cada 2 horas"),
        (["5 * * * *"], "A cada hora, no minuto 5"),
        (["0 9 L * *"], "No último dia do mês às 09:00"),
        (["0 0 1,15 * *"], "Nos dias 1 e 15 de cada mês às 00:00"),
        (["0 8 * * 0,6"], "Aos sábados e domingos às 08:00"),
        (["0 8 * * 6"], "Todo sábado às 08:00"),
        (["0 0 13 * 5"], "No dia 13 de cada mês ou toda sexta às 00:00"),
        (["*/10 8-17 * * 1-5"], "A cada 10 minutos, das 08h às 17h, de segunda a sexta"),
        (["0 9 1 1,7 *"], "No dia 1 de cada mês às 09:00, em janeiro e julho"),
        (["* * * * *"], "A cada minuto"),
        (["0 8 * * 1", "0 9 * * 2"], "Toda segunda às 08:00; Toda terça às 09:00"),
        ([], "Sem agendamento (apenas execução manual)"),
    ],
)
def test_describe(expressions, expected):
    assert describe(expressions) == expected


def test_describe_invalid():
    with pytest.raises(CronError):
        describe(["bad"])


def test_preview_and_task_include_description(client, make):
    body = client.post(
        f"{API}/schedule/preview", json={"cron_expressions": ["30 8 * * 1,3"]}
    ).json()
    assert body["description"] == "Toda segunda e quarta às 08:30"
    g, s, t = make.tree()
    assert t["schedule_description"] == "Todos os dias às 08:00"


def _finish(db, task_id, status):
    run = create_run(db, task_id, RunTrigger.MANUAL)
    run.status = status
    run.finished_at = datetime.now(UTC)
    db.commit()
    return run


def test_tree_with_status_indicators(client, make, db):
    g = make.group("b-grupo")
    make.group("a-grupo", is_active=False)
    s = make.subcategory(g["id"], "s")
    ok = make.task(s["id"], "ok")
    bad = make.task(s["id"], "bad")
    _finish(db, ok["id"], RunStatus.SUCCESS)
    _finish(db, bad["id"], RunStatus.SUCCESS)
    _finish(db, bad["id"], RunStatus.FAILED)
    _finish(db, bad["id"], RunStatus.SKIPPED)  # skips don't hide the failure
    running = create_run(db, ok["id"], RunTrigger.MANUAL)
    running.status = RunStatus.RUNNING
    db.commit()

    tree = client.get(f"{API}/tree").json()
    assert [x["name"] for x in tree] == ["a-grupo", "b-grupo"]
    assert tree[0]["is_active"] is False and tree[0]["subcategories"] == []
    grp = tree[1]
    assert grp["has_failure"] is True
    sub = grp["subcategories"][0]
    assert sub["has_failure"] is True
    tasks = {t["name"]: t for t in sub["tasks"]}
    assert tasks["bad"]["last_run_status"] == "failed"
    assert tasks["ok"]["last_run_status"] == "success" and tasks["ok"]["running"] is True


def test_dashboard(client, make, db):
    g, s, t = make.tree()
    paused = make.task(s["id"], "pausada", is_active=False)
    _finish(db, t["id"], RunStatus.SUCCESS)
    _finish(db, t["id"], RunStatus.SUCCESS)
    _finish(db, t["id"], RunStatus.SUCCESS)
    _finish(db, paused["id"], RunStatus.TIMEOUT)

    body = client.get(f"{API}/dashboard").json()
    assert body["counts"] == {
        "groups": 1, "subcategories": 1, "tasks": 2, "tasks_active": 1, "tasks_paused": 1,
    }  # fmt: skip
    assert body["stats"]["last_24h"]["success_rate"] == 0.75
    assert body["stats"]["last_7d"]["total"] == 4
    assert [r["status"] for r in body["recent_failures"]] == ["timeout"]
    assert body["running"] == []
    assert body["upcoming"] and all(u["task_id"] == t["id"] for u in body["upcoming"])
    assert body["worker"]["online"] is False

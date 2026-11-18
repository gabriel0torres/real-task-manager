"""Notifications: config API, event detection, delivery, retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from rts.engine.context import EngineContext
from rts.engine.scheduler import SchedulerEngine
from rts.models import Run, RunLogChunk, RunStatus, RunTrigger, Setting
from rts.notifications import channels
from rts.notifications.service import Notifier
from rts.services.retention import apply_retention
from rts.services.runs import append_system_log, create_run
from tests.conftest import API


@pytest.fixture
def sent(monkeypatch):
    """Capture deliveries instead of talking to SMTP/Telegram/webhooks."""
    calls: list[tuple] = []

    def fake_email(cfg, to, subject, body):
        if cfg.host == "falha.invalid":
            raise channels.ChannelError("SMTP recusou")
        calls.append(("email", tuple(to), subject, body, cfg))

    monkeypatch.setattr(channels, "send_email", fake_email)
    monkeypatch.setattr(
        channels,
        "send_telegram",
        lambda token, chat, text: calls.append(("telegram", chat, token, text)),
    )
    monkeypatch.setattr(
        channels, "send_webhook", lambda url, payload: calls.append(("webhook", url, payload))
    )
    return calls


@pytest.fixture
def engine(app):
    notifier = Notifier(
        app.state.session_factory, app.state.secret_box, app.state.settings, synchronous=True
    )
    eng = SchedulerEngine(
        EngineContext(
            app.state.settings, app.state.session_factory, app.state.secret_box, notifier=notifier
        )
    )
    yield eng
    eng.stop()


def _task(make, command="import sys; sys.exit(1)", **kw):
    g = make.group()
    s = make.subcategory(g["id"])
    return make.task(s["id"], shell="python", command=command, cron_expressions=[], **kw)


def _run(engine, client, task_id) -> int:
    run_id = client.post(f"{API}/tasks/{task_id}/run").json()["id"]
    engine.dispatch()
    assert engine.wait_idle(30)
    return run_id


def _rule(client, **kw):
    body = {"email_to": ["ops@empresa.com"], **kw}
    resp = client.put(f"{API}/notifications/rules/global", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _log(db, run_id) -> str:
    db.expire_all()
    return "".join(
        c.content for c in db.scalars(select(RunLogChunk).where(RunLogChunk.run_id == run_id))
    )


# --------------------------------------------------------------------------- config API
def test_channels_secrets_are_encrypted_and_write_only(client, db):
    body = {
        "smtp": {
            "host": "smtp.empresa.com",
            "port": 465,
            "security": "ssl",
            "username": "rts",
            "sender": "rts@empresa.com",
            "password": "smtp-senha",
        },
        "telegram": {"bot_token": "123:ABC"},
    }
    out = client.put(f"{API}/notifications/channels", json=body).json()
    assert out["smtp"]["has_password"] is True and out["telegram"]["has_bot_token"] is True
    assert "smtp-senha" not in str(out) and "123:ABC" not in str(out)
    stored = str(db.get(Setting, "notification_channels").value)
    assert "smtp-senha" not in stored and "123:ABC" not in stored

    # omitted password keeps it; "" clears it
    out = client.put(f"{API}/notifications/channels", json={"smtp": {"port": 587}}).json()
    assert out["smtp"]["has_password"] is True and out["smtp"]["port"] == 587
    out = client.put(f"{API}/notifications/channels", json={"smtp": {"password": ""}}).json()
    assert out["smtp"]["has_password"] is False


def test_rules_validation_and_group_override(client, make):
    assert client.get(f"{API}/notifications/rules/global").json()["exists"] is False
    bad = client.put(f"{API}/notifications/rules/global", json={"email_to": ["não-é-email"]})
    assert bad.status_code == 422
    bad = client.put(f"{API}/notifications/rules/global", json={"webhook_urls": ["ftp://x"]})
    assert bad.status_code == 422
    bad = client.put(f"{API}/notifications/rules/global", json={"telegram_chat_ids": ["abc"]})
    assert bad.status_code == 422

    _rule(client, telegram_chat_ids=["-1001234", "@canal_ops"])
    g = make.group()
    inherited = client.get(f"{API}/notifications/rules/groups/{g['id']}").json()
    assert inherited["uses_own_rule"] is False and inherited["rule"]["email_to"] == [
        "ops@empresa.com"
    ]

    own = client.put(f"{API}/notifications/rules/groups/{g['id']}", json={"enabled": False}).json()
    assert own["uses_own_rule"] is True and own["rule"]["enabled"] is False
    assert client.delete(f"{API}/notifications/rules/groups/{g['id']}").status_code == 204
    assert (
        client.get(f"{API}/notifications/rules/groups/{g['id']}").json()["uses_own_rule"] is False
    )


def test_send_test_message(client, sent, monkeypatch):
    resp = client.post(
        f"{API}/notifications/test", json={"channel": "webhook", "target": "https://h.example/x"}
    )
    assert resp.json() == {"ok": True, "error": None}
    assert sent[0][0] == "webhook" and sent[0][2]["event"] == "test"

    def boom(*_a):
        raise channels.ChannelError("Token do bot do Telegram não configurado.")

    monkeypatch.setattr(channels, "send_telegram", boom)
    resp = client.post(
        f"{API}/notifications/test", json={"channel": "telegram", "target": "123"}
    ).json()
    assert resp == {"ok": False, "error": "Token do bot do Telegram não configurado."}


# --------------------------------------------------------------------------- events
def test_failure_notifies_all_channels_with_log_tail(engine, client, make, db, sent):
    client.put(
        f"{API}/notifications/channels",
        json={"smtp": {"host": "smtp.x", "sender": "rts@x"}, "telegram": {"bot_token": "bot:1"}},
    )
    _rule(client, telegram_chat_ids=["42"], webhook_urls=["https://hook.example/rts"])
    t = _task(make, command="print('conectando no banco')\nimport sys; sys.exit(3)")
    run_id = _run(engine, client, t["id"])

    kinds = [c[0] for c in sent]
    assert kinds == ["email", "telegram", "webhook"]
    _, to, subject, body, cfg = sent[0]
    assert to == ("ops@empresa.com",) and cfg.host == "smtp.x"
    assert subject == "[RTS] Falha: instagram / postagens / publicar"
    assert "Código de saída 3." in body and "conectando no banco" in body
    assert sent[1][2] == "bot:1"  # decrypted bot token
    payload = sent[2][2]
    assert payload["event"] == "failure" and payload["run"]["exit_code"] == 3
    assert "Notificação enviada: e-mail (ops@empresa.com); Telegram (42); webhook" in _log(
        db, run_id
    )


def test_failure_with_pending_retry_is_not_notified(engine, client, make, sent):
    _rule(client)
    t = _task(make, max_retries=1, retry_interval_seconds=0)
    _run(engine, client, t["id"])
    assert sent == []  # retry pending
    engine.dispatch()
    assert engine.wait_idle(30)
    assert len(sent) == 1 and "tentativa 2" in sent[0][3]


def test_success_recovery_and_disabled_rules(engine, client, make, db, sent):
    _rule(client, on_failure=False, on_recovery=True)
    t = _task(make)
    _run(engine, client, t["id"])
    assert sent == []  # failure off

    client.patch(f"{API}/tasks/{t['id']}", json={"command": "print('ok')"})
    _run(engine, client, t["id"])
    assert len(sent) == 1 and sent[0][2].startswith("[RTS] Voltou ao normal")
    _run(engine, client, t["id"])
    assert len(sent) == 1  # plain success not requested

    client.put(f"{API}/notifications/rules/groups/{t['group_id']}", json={"enabled": False})
    client.patch(f"{API}/tasks/{t['id']}", json={"command": "import sys; sys.exit(1)"})
    _run(engine, client, t["id"])
    assert len(sent) == 1  # group override disables


def test_delivery_errors_are_logged_in_the_run(engine, client, make, db, sent):
    client.put(
        f"{API}/notifications/channels", json={"smtp": {"host": "falha.invalid", "sender": "a@b"}}
    )
    _rule(client)
    t = _task(make)
    run_id = _run(engine, client, t["id"])
    assert "Notificação falhou - e-mail: SMTP recusou" in _log(db, run_id)
    assert db.get(Run, run_id).status is RunStatus.FAILED  # the run itself is unaffected


def test_timeout_event(engine, client, make, sent):
    _rule(client)
    t = _task(make, command="import time; time.sleep(30)", timeout_seconds=1)
    _run(engine, client, t["id"])
    assert sent[0][2].startswith("[RTS] Tempo esgotado")


# --------------------------------------------------------------------------- retention
def _old_run(db, task_id, days_ago, status=RunStatus.SUCCESS):
    run = create_run(db, task_id, RunTrigger.MANUAL)
    run.created_at = datetime.now(UTC) - timedelta(days=days_ago)
    run.status = status
    append_system_log(db, run.id, "x")
    db.commit()
    return run.id


def test_retention_by_age_and_count(client, make, db):
    t = _task(make)
    old = [_old_run(db, t["id"], 40), _old_run(db, t["id"], 31)]
    recent = [_old_run(db, t["id"], d) for d in (5, 3, 2, 1)]
    running = create_run(db, t["id"], RunTrigger.MANUAL)
    running.status = RunStatus.RUNNING
    running.created_at = datetime.now(UTC) - timedelta(days=90)
    db.commit()

    resp = client.patch(f"{API}/settings", json={"retention_days": 30, "retention_keep_last": 3})
    assert resp.json()["retention_days"] == 30 and resp.json()["retention_keep_last"] == 3
    assert client.post(f"{API}/settings/retention/apply").json() == {"deleted": 3}

    db.expire_all()
    remaining = set(db.scalars(select(Run.id)))
    assert remaining == {*recent[1:], running.id}  # oldest recent dropped by keep_last
    assert not set(old) & remaining
    chunks = db.scalar(select(func.count(RunLogChunk.id)).where(RunLogChunk.run_id.in_(old)))
    assert chunks == 0  # logs removed with their runs

    resp = client.patch(f"{API}/settings", json={"retention_days": None})
    assert resp.json()["retention_days"] is None and resp.json()["retention_keep_last"] == 3
    assert client.patch(f"{API}/settings", json={"retention_days": 0}).status_code == 422


def test_retention_disabled_by_default(app, make, db):
    t = _task(make)
    _old_run(db, t["id"], 1000)
    assert apply_retention(db, datetime.now(UTC)) == 0

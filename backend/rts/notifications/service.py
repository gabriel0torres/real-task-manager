"""Notification configuration, event detection and dispatch.

* Channels (SMTP server, Telegram bot) are global; their secrets are encrypted.
* Rules say *when* (failure, timeout, success, recovery) and *to whom*. There is a
  global rule; a group may have its own rule, which then replaces the global one.
* A failure is notified only when the run is final (no retry pending), so a task
  that fails and then succeeds on the retry does not page anyone.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from rts.config import Settings
from rts.models import LogStream, NotificationRule, Run, RunLogChunk, RunStatus, RunTrigger
from rts.notifications import channels
from rts.security.crypto import SecretBox, SecretDecryptError
from rts.services.runs import append_system_log
from rts.services.settings import get_setting, set_setting

log = logging.getLogger(__name__)

CHANNELS_KEY = "notification_channels"
EVENT_LABELS = {
    "failure": "Falha",
    "timeout": "Tempo esgotado",
    "success": "Sucesso",
    "recovery": "Voltou ao normal",
}
STATUS_LABELS = {
    RunStatus.SUCCESS: "sucesso",
    RunStatus.FAILED: "falha",
    RunStatus.TIMEOUT: "tempo esgotado",
}
LOG_TAIL_LINES = 20


# --------------------------------------------------------------------------- channels config
def _raw_channels(session: Session) -> dict:
    return dict(get_setting(session, CHANNELS_KEY, {}) or {})


def channels_public(session: Session) -> dict:
    raw = _raw_channels(session)
    smtp = dict(raw.get("smtp") or {})
    has_password = bool(smtp.pop("password", None))
    telegram = raw.get("telegram") or {}
    return {
        "smtp": {
            "host": smtp.get("host", ""),
            "port": smtp.get("port", 587),
            "security": smtp.get("security", "starttls"),
            "username": smtp.get("username", ""),
            "sender": smtp.get("sender", ""),
            "has_password": has_password,
        },
        "telegram": {"has_bot_token": bool(telegram.get("bot_token"))},
    }


def update_channels(session: Session, box: SecretBox, data: dict) -> dict:
    """``password``/``bot_token``: None keeps the current value, "" clears it."""
    raw = _raw_channels(session)
    if "smtp" in data and data["smtp"] is not None:
        smtp_in = dict(data["smtp"])
        current = dict(raw.get("smtp") or {})
        password = smtp_in.pop("password", None)
        smtp = {**current, **{k: v for k, v in smtp_in.items() if v is not None}}
        if password is not None:
            smtp["password"] = box.encrypt(password) if password else None
        raw["smtp"] = smtp
    if "telegram" in data and data["telegram"] is not None:
        token = data["telegram"].get("bot_token")
        current = dict(raw.get("telegram") or {})
        if token is not None:
            current["bot_token"] = box.encrypt(token) if token else None
        raw["telegram"] = current
    set_setting(session, CHANNELS_KEY, raw)
    session.flush()
    return channels_public(session)


def _decrypt(box: SecretBox, value: str | None) -> str | None:
    if not value:
        return None
    try:
        return box.decrypt(value)
    except SecretDecryptError:
        log.error("Não foi possível decifrar um segredo das notificações (RTS_SECRET_KEY mudou?).")
        return None


def load_smtp(session: Session, box: SecretBox) -> channels.SmtpConfig:
    smtp = _raw_channels(session).get("smtp") or {}
    return channels.SmtpConfig(
        host=smtp.get("host", ""),
        port=int(smtp.get("port") or 587),
        security=smtp.get("security", "starttls"),
        username=smtp.get("username") or None,
        password=_decrypt(box, smtp.get("password")),
        sender=smtp.get("sender", ""),
    )


def load_telegram_token(session: Session, box: SecretBox) -> str | None:
    return _decrypt(box, (_raw_channels(session).get("telegram") or {}).get("bot_token"))


# --------------------------------------------------------------------------- rules
RULE_FIELDS = (
    "enabled",
    "on_failure",
    "on_timeout",
    "on_success",
    "on_recovery",
    "email_to",
    "telegram_chat_ids",
    "webhook_urls",
)


def get_rule(session: Session, group_id: int | None) -> NotificationRule | None:
    stmt = select(NotificationRule).where(
        NotificationRule.group_id.is_(None)
        if group_id is None
        else NotificationRule.group_id == group_id
    )
    return session.scalars(stmt).first()


def effective_rule(session: Session, group_id: int) -> NotificationRule | None:
    return get_rule(session, group_id) or get_rule(session, None)


def save_rule(session: Session, group_id: int | None, data: dict) -> NotificationRule:
    rule = get_rule(session, group_id)
    if rule is None:
        rule = NotificationRule(group_id=group_id)
        session.add(rule)
    for name in RULE_FIELDS:
        if name in data:
            setattr(rule, name, data[name])
    session.flush()
    return rule


def delete_group_rule(session: Session, group_id: int) -> None:
    rule = get_rule(session, group_id)
    if rule is not None:
        session.delete(rule)
        session.flush()


# --------------------------------------------------------------------------- events
def _chain_id(run: Run) -> int:
    return run.root_run_id or run.id


def classify(session: Session, run: Run) -> set[str]:
    """Events this finished run represents (empty = nothing to notify)."""
    if run.status in (RunStatus.FAILED, RunStatus.TIMEOUT):
        chain = _chain_id(run)
        retry_pending = session.scalar(
            select(Run.id).where(
                Run.root_run_id == chain,
                Run.attempt > run.attempt,
                Run.trigger == RunTrigger.RETRY,
            )
        )
        if retry_pending is not None:
            return set()
        return {"failure" if run.status is RunStatus.FAILED else "timeout"}
    if run.status is RunStatus.SUCCESS:
        events = {"success"}
        chain = _chain_id(run)
        previous = session.scalars(
            select(Run.status)
            .where(
                Run.task_id == run.task_id,
                Run.id < run.id,
                Run.id != chain,
                (Run.root_run_id.is_(None)) | (Run.root_run_id != chain),
                Run.status.in_([RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.TIMEOUT]),
            )
            .order_by(Run.id.desc())
            .limit(1)
        ).first()
        if previous in (RunStatus.FAILED, RunStatus.TIMEOUT):
            events.add("recovery")
        return events
    return set()


def wanted(rule: NotificationRule, events: set[str]) -> str | None:
    """The event to announce under this rule (most important first)."""
    if not rule.enabled:
        return None
    for event, flag in (
        ("failure", rule.on_failure),
        ("timeout", rule.on_timeout),
        ("recovery", rule.on_recovery),
        ("success", rule.on_success),
    ):
        if event in events and flag:
            return event
    return None


# --------------------------------------------------------------------------- message
@dataclass
class Message:
    subject: str
    text: str
    payload: dict = field(default_factory=dict)


def _log_tail(session: Session, run_id: int) -> str:
    chunks = session.scalars(
        select(RunLogChunk.content)
        .where(RunLogChunk.run_id == run_id, RunLogChunk.stream != LogStream.SYSTEM)
        .order_by(RunLogChunk.seq.desc())
        .limit(50)
    ).all()
    lines = "".join(reversed(chunks)).splitlines()
    return "\n".join(lines[-LOG_TAIL_LINES:])


def build_message(session: Session, run: Run, event: str, public_url: str | None) -> Message:
    task = run.task
    sub = task.subcategory
    group = sub.group
    path = f"{group.name} / {sub.name} / {task.name}"
    url = f"{public_url.rstrip('/')}/runs/{run.id}" if public_url else None
    duration = f"{run.duration_ms / 1000:.1f}s" if run.duration_ms is not None else "—"
    tail = _log_tail(session, run.id)
    status_label = STATUS_LABELS.get(run.status, run.status)
    lines = [
        f"{EVENT_LABELS[event]}: {path}",
        f"Execução #{run.id} (tentativa {run.attempt}) - {status_label}",
    ]
    if run.status_reason:
        lines.append(f"Motivo: {run.status_reason}")
    lines.append(f"Duração: {duration}")
    if url:
        lines.append(f"Detalhes: {url}")
    if tail and event != "success":
        lines += ["", "Últimas linhas do log:", tail]
    payload = {
        "event": event,
        "event_label": EVENT_LABELS[event],
        "task": {"id": task.id, "name": task.name, "subcategory": sub.name, "group": group.name},
        "run": {
            "id": run.id,
            "status": run.status.value,
            "trigger": run.trigger.value,
            "attempt": run.attempt,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "duration_ms": run.duration_ms,
            "exit_code": run.exit_code,
            "reason": run.status_reason,
            "url": url,
        },
        "log_tail": tail,
    }
    return Message(
        subject=f"[RTS] {EVENT_LABELS[event]}: {path}", text="\n".join(lines), payload=payload
    )


# --------------------------------------------------------------------------- dispatch
def deliver(
    session: Session, box: SecretBox, rule: NotificationRule, message: Message
) -> tuple[list[str], list[str]]:
    """Send through every target of the rule. Returns (sent, errors) descriptions."""
    sent: list[str] = []
    errors: list[str] = []
    if rule.email_to:
        try:
            channels.send_email(
                load_smtp(session, box), rule.email_to, message.subject, message.text
            )
            sent.append(f"e-mail ({', '.join(rule.email_to)})")
        except channels.ChannelError as exc:
            errors.append(f"e-mail: {exc}")
    if rule.telegram_chat_ids:
        token = load_telegram_token(session, box)
        for chat in rule.telegram_chat_ids:
            try:
                channels.send_telegram(token or "", chat, message.text)
                sent.append(f"Telegram ({chat})")
            except channels.ChannelError as exc:
                errors.append(f"Telegram {chat}: {exc}")
    for url in rule.webhook_urls:
        try:
            channels.send_webhook(url, {**message.payload, "message": message.text})
            sent.append(f"webhook ({url})")
        except channels.ChannelError as exc:
            errors.append(f"webhook {url}: {exc}")
    return sent, errors


class Notifier:
    """Called by the engine when a run finishes; sends in a background thread."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        box: SecretBox,
        settings: Settings,
        *,
        synchronous: bool = False,
    ) -> None:
        self.session_factory = session_factory
        self.box = box
        self.settings = settings
        self.synchronous = synchronous
        self._pool = None if synchronous else ThreadPoolExecutor(2, thread_name_prefix="rts-notify")

    def notify_run(self, run_id: int) -> None:
        if self._pool is None:
            self._process(run_id)
        else:
            self._pool.submit(self._process, run_id)

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)

    def _process(self, run_id: int) -> None:
        try:
            with self.session_factory() as session:
                run = session.get(Run, run_id)
                if run is None:
                    return
                rule = effective_rule(session, run.task.subcategory.group_id)
                if rule is None:
                    return
                event = wanted(rule, classify(session, run))
                if event is None:
                    return
                message = build_message(session, run, event, self.settings.public_url)
                sent, errors = deliver(session, self.box, rule, message)
                if sent:
                    append_system_log(session, run.id, "Notificação enviada: " + "; ".join(sent))
                for error in errors:
                    append_system_log(session, run.id, f"Notificação falhou - {error}")
                session.commit()
        except Exception:  # pragma: no cover - never break the engine
            log.exception("Erro ao processar notificações da execução %s", run_id)

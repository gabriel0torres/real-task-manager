"""Build export files from the database (run history is never exported)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rts import __version__
from rts.models import Group, ScheduleMode, Subcategory, Task, Variable, VariableScope
from rts.scheduling.cron import CronError
from rts.scheduling.describe import describe
from rts.security.crypto import SecretBox
from rts.services.hierarchy import get_group, get_subcategory
from rts.services.settings import get_default_timezone
from rts.transfer.crypto import ExportCipher
from rts.transfer.format import SCHEMA_VERSION, Scope, SecretsMode, dump_document

SCOPE_LABELS = {"system": "sistema inteiro", "group": "grupo", "subcategory": "subcategoria"}
INHERITED_FROM = {"subcategory": "da subcategoria", "group": "do grupo"}


def _describe(expressions) -> str | None:
    try:
        return describe(list(expressions))
    except CronError:
        return None


def _owner_schedule(crons: list[str], timezone: str | None, note: str = "") -> dict:
    description = _describe(crons)
    return {
        "cron": list(crons),
        "timezone": timezone,
        "description": f"{description}{note}" if description else None,
    }


@dataclass
class ExportResult:
    content: str
    filename: str
    secrets_total: int


class _Writer:
    def __init__(self, session: Session, box: SecretBox, cipher: ExportCipher | None) -> None:
        self.session = session
        self.box = box
        self.cipher = cipher
        self.secrets_total = 0
        # Lowest schema version the content needs (see rts.transfer.format).
        self.version = 1

    def variables(self, scope: VariableScope, owner_id: int | None) -> list[dict]:
        stmt = select(Variable).where(Variable.scope == scope)
        if scope is not VariableScope.GLOBAL:
            column = {
                VariableScope.GROUP: Variable.group_id,
                VariableScope.SUBCATEGORY: Variable.subcategory_id,
                VariableScope.TASK: Variable.task_id,
            }[scope]
            stmt = stmt.where(column == owner_id)
        out = []
        for var in self.session.scalars(stmt.order_by(Variable.key)):
            item: dict = {"key": var.key}
            if var.is_secret:
                self.secrets_total += 1
                item["secret"] = True
                if self.cipher is not None and var.value is not None:
                    item["value_encrypted"] = self.cipher.encrypt(self.box.decrypt(var.value))
                else:
                    item["value"] = None  # "a preencher" on import
            else:
                item["value"] = var.value
            if var.description:
                item["description"] = var.description
            out.append(item)
        return out

    def schedule(self, task: Task) -> dict:
        if task.schedule_mode is ScheduleMode.INHERIT:
            self.version = max(self.version, 2)
            effective = task.effective_schedule
            if effective:
                description = f"herdado {INHERITED_FROM[effective.source]}: " + (
                    _describe(effective.expressions) or "agendamento inválido"
                )
            else:
                description = "herdado, mas a subcategoria e o grupo não têm agendamento"
            # cron/timezone: the task's own schedule, kept for when it stops inheriting.
            return {
                "mode": ScheduleMode.INHERIT.value,
                "cron": list(task.cron_expressions),
                "timezone": task.timezone,
                "description": description,
            }
        if task.schedule_mode is ScheduleMode.MANUAL:
            # An empty schedule already means "manual" in version 1.
            return {"cron": [], "timezone": task.timezone, "description": _describe([])}
        return _owner_schedule(task.cron_expressions, task.timezone)

    def task(self, task: Task) -> dict:
        data = {
            "name": task.name,
            "description": task.description,
            "command": task.command,
            "shell": task.shell.value if task.shell else None,
            "working_dir": task.working_dir,
            "active": task.is_active,
            "schedule": self.schedule(task),
            "timeout_seconds": task.timeout_seconds,
            "retries": {"max": task.max_retries, "interval_seconds": task.retry_interval_seconds},
            "overlap_policy": task.overlap_policy.value,
            "misfire_policy": task.misfire_policy.value,
            "variables": self.variables(VariableScope.TASK, task.id),
        }
        if task.sequence_position is not None:
            self.version = max(self.version, 3)
            data["sequence_position"] = task.sequence_position
        return data

    def subcategory(self, sub: Subcategory, standalone: bool = False) -> dict:
        tasks = sorted(sub.tasks, key=lambda t: t.name.lower())
        data: dict = {
            "name": sub.name,
            "description": sub.description,
            "active": sub.is_active,
            "variables": self.variables(VariableScope.SUBCATEGORY, sub.id),
        }
        if sub.cron_expressions:
            data["schedule"] = _owner_schedule(sub.cron_expressions, sub.timezone)
        elif standalone and sub.group.cron_expressions:
            # Exported without its group: carry the group's schedule, so tasks that
            # inherit it keep the same schedule wherever the file is imported.
            group = sub.group
            data["schedule"] = _owner_schedule(
                group.cron_expressions, group.timezone, f" (do grupo {group.name})"
            )
        if "schedule" in data:
            self.version = max(self.version, 2)
        if sub.is_sequential or sub.stop_on_failure:
            self.version = max(self.version, 3)
            data["execution"] = {
                "mode": sub.execution_mode.value,
                "stop_on_failure": sub.stop_on_failure,
            }
        data["tasks"] = [self.task(t) for t in tasks]
        return data

    def group(self, group: Group, only: Subcategory | None = None) -> dict:
        subs = [only] if only else sorted(group.subcategories, key=lambda s: s.name.lower())
        data: dict = {
            "name": group.name,
            "description": group.description,
            "active": group.is_active,
            "variables": [] if only else self.variables(VariableScope.GROUP, group.id),
        }
        if not only and group.cron_expressions:
            self.version = max(self.version, 2)
            data["schedule"] = _owner_schedule(group.cron_expressions, group.timezone)
        data["subcategories"] = [self.subcategory(s, standalone=only is not None) for s in subs]
        return data


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "export"


def export_config(
    session: Session,
    box: SecretBox,
    *,
    scope: Scope,
    target_id: int | None = None,
    secrets_mode: SecretsMode = "omit",
    password: str | None = None,
    fallback_timezone: str = "UTC",
    now: datetime | None = None,
) -> ExportResult:
    cipher = None
    if secrets_mode == "encrypted":
        if not password:
            raise ValueError("Informe uma senha para cifrar os segredos.")
        cipher = ExportCipher.create(password)
    writer = _Writer(session, box, cipher)
    now = (now or datetime.now(UTC)).replace(microsecond=0)

    doc: dict = {
        "schema_version": 1,  # raised below if the content needs a newer version
        "rts_version": __version__,
        "exported_at": now.isoformat().replace("+00:00", "Z"),
        "scope": scope,
        "secrets_mode": secrets_mode,
    }
    if cipher is not None:
        doc["encryption"] = cipher.header()

    if scope == "system":
        doc["settings"] = {"default_timezone": get_default_timezone(session, fallback_timezone)}
        doc["variables"] = writer.variables(VariableScope.GLOBAL, None)
        groups = session.scalars(select(Group).order_by(func.lower(Group.name))).all()
        doc["groups"] = [writer.group(g) for g in groups]
        label = "sistema"
    elif scope == "group":
        if target_id is None:
            raise ValueError("Informe o grupo a exportar.")
        group = get_group(session, target_id)
        doc["groups"] = [writer.group(group)]
        label = group.name
    else:
        if target_id is None:
            raise ValueError("Informe a subcategoria a exportar.")
        sub = get_subcategory(session, target_id)
        doc["groups"] = [writer.group(sub.group, only=sub)]
        label = f"{sub.group.name}-{sub.name}"

    doc["schema_version"] = writer.version
    assert writer.version <= SCHEMA_VERSION

    secrets_note = {
        "omit": "segredos exportados SEM valor (a preencher na importação)",
        "encrypted": "segredos CIFRADOS com a senha informada na exportação",
    }[secrets_mode]
    header = (
        f"Real Task Scheduler - exportação ({SCOPE_LABELS[scope]})\n"
        f"Gerado em {doc['exported_at']} pelo RTS {__version__}; {secrets_note}.\n"
        "O histórico de execuções não é exportado."
    )
    filename = f"rts-{scope}-{_slug(label)}-{now.strftime('%Y%m%d-%H%M%S')}.yaml"
    return ExportResult(dump_document(doc, header), filename, writer.secrets_total)

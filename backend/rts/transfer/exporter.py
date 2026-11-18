"""Build export files from the database (run history is never exported)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rts import __version__
from rts.models import Group, Subcategory, Task, Variable, VariableScope
from rts.scheduling.cron import CronError
from rts.scheduling.describe import describe
from rts.security.crypto import SecretBox
from rts.services.hierarchy import get_group, get_subcategory
from rts.services.settings import get_default_timezone
from rts.transfer.crypto import ExportCipher
from rts.transfer.format import SCHEMA_VERSION, Scope, SecretsMode, dump_document

SCOPE_LABELS = {"system": "sistema inteiro", "group": "grupo", "subcategory": "subcategoria"}


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

    def task(self, task: Task) -> dict:
        try:
            description = describe(task.cron_expressions)
        except CronError:
            description = None
        data = {
            "name": task.name,
            "description": task.description,
            "command": task.command,
            "shell": task.shell.value if task.shell else None,
            "working_dir": task.working_dir,
            "active": task.is_active,
            "schedule": {
                "cron": list(task.cron_expressions),
                "timezone": task.timezone,
                "description": description,
            },
            "timeout_seconds": task.timeout_seconds,
            "retries": {"max": task.max_retries, "interval_seconds": task.retry_interval_seconds},
            "overlap_policy": task.overlap_policy.value,
            "misfire_policy": task.misfire_policy.value,
            "variables": self.variables(VariableScope.TASK, task.id),
        }
        return data

    def subcategory(self, sub: Subcategory) -> dict:
        tasks = sorted(sub.tasks, key=lambda t: t.name.lower())
        return {
            "name": sub.name,
            "description": sub.description,
            "active": sub.is_active,
            "variables": self.variables(VariableScope.SUBCATEGORY, sub.id),
            "tasks": [self.task(t) for t in tasks],
        }

    def group(self, group: Group, only: Subcategory | None = None) -> dict:
        subs = [only] if only else sorted(group.subcategories, key=lambda s: s.name.lower())
        return {
            "name": group.name,
            "description": group.description,
            "active": group.is_active,
            "variables": [] if only else self.variables(VariableScope.GROUP, group.id),
            "subcategories": [self.subcategory(s) for s in subs],
        }


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
        "schema_version": SCHEMA_VERSION,
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

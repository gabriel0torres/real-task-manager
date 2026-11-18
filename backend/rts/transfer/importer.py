"""Import of export files: validation, dry-run plan, conflict resolution, atomic apply.

The preview *is* the import: the same code runs inside a transaction which is
rolled back for a dry run and committed otherwise, so what the user sees in the
plan is exactly what gets applied (and an error anywhere leaves nothing behind).

Conflict resolutions (by entity name, case-insensitive, at the same level):

* ``overwrite`` - the existing entity becomes exactly what the file says: fields,
  variables and children (children missing from the file are deleted);
* ``merge``     - fields come from the file, variables are upserted (file wins),
  existing children are kept and the file's children are merged one by one
  (each child conflict gets its own resolution);
* ``rename``    - the file's entity is created alongside, under a new name;
* ``skip``      - nothing changes (default when no resolution is given).

Global variables follow the same idea with ``overwrite``/``merge``/``skip``.
Tasks written by the import are paused unless ``activate_tasks`` is set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rts.models import (
    ExecutionMode,
    Group,
    ScheduleMode,
    Subcategory,
    Task,
    Variable,
    VariableScope,
)
from rts.scheduling.cron import CronError
from rts.scheduling.describe import describe
from rts.security.crypto import SecretBox, SecretDecryptError
from rts.services.settings import (
    DEFAULT_TIMEZONE,
    bump_config_revision,
    get_default_timezone,
    set_setting,
)
from rts.transfer.crypto import ExportCipher, WrongPasswordError
from rts.transfer.format import (
    MAX_FILE_BYTES,
    ExecutionDoc,
    ExportDoc,
    FileError,
    GroupDoc,
    ScheduleDoc,
    SubcategoryDoc,
    TaskDoc,
    VariableDoc,
    parse_document,
)

Action = Literal["overwrite", "merge", "rename", "skip"]
ENTITY_RESOLUTIONS: list[Action] = ["overwrite", "merge", "rename", "skip"]
GLOBAL_RESOLUTIONS: list[Action] = ["overwrite", "merge", "skip"]
KIND_LABELS = {"group": "grupo", "subcategory": "subcategoria", "task": "tarefa"}


# --------------------------------------------------------------------------- request/report
class Resolution(BaseModel):
    action: Action
    new_name: str | None = Field(default=None, max_length=100)


class ImportOptions(BaseModel):
    content: str = Field(max_length=MAX_FILE_BYTES)
    password: str | None = None
    resolutions: dict[str, Resolution] = Field(default_factory=dict)
    activate_tasks: bool = False
    apply_settings: bool = True
    secret_values: dict[str, str] = Field(
        default_factory=dict, description="Valores para segredos sem valor, por caminho."
    )
    target_group_id: int | None = Field(
        default=None, description="Somente para exportações de subcategoria: grupo de destino."
    )


class PlanItem(BaseModel):
    path: str
    kind: Literal["settings", "globals", "group", "subcategory", "task"]
    name: str
    depth: int
    action: Literal["create", "update", "delete", "skip", "unchanged", "rename"]
    conflict: bool = False
    resolution: Action | None = None
    allowed_resolutions: list[Action] = Field(default_factory=list)
    new_name: str | None = None
    details: list[str] = Field(default_factory=list)


class PendingSecret(BaseModel):
    path: str
    key: str
    owner: str


class ImportReport(BaseModel):
    valid: bool
    applied: bool = False
    errors: list[str] = Field(default_factory=list)
    header: dict | None = None
    needs_password: bool = False
    password_ok: bool | None = None
    items: list[PlanItem] = Field(default_factory=list)
    pending_secrets: list[PendingSecret] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    tasks_paused: bool = True


class ImportFailure(Exception):
    pass


# --------------------------------------------------------------------------- engine
_TASK_LABELS = {
    "description": "descrição",
    "command": "comando",
    "shell": "interpretador",
    "working_dir": "diretório de trabalho",
    "schedule_mode": "origem do agendamento",
    "cron_expressions": "agendamento",
    "timezone": "fuso horário",
    "timeout_seconds": "timeout",
    "max_retries": "novas tentativas",
    "retry_interval_seconds": "intervalo entre tentativas",
    "overlap_policy": "sobreposição",
    "misfire_policy": "execuções perdidas",
    "sequence_position": "ordem na sequência",
    "is_active": "ativa",
}


def _task_fields(t: TaskDoc) -> dict:
    return {
        "description": t.description,
        "command": t.command,
        "shell": t.shell,
        "working_dir": t.working_dir,
        "schedule_mode": t.schedule.effective_mode,
        "cron_expressions": list(t.schedule.cron),
        "timezone": t.schedule.timezone,
        "timeout_seconds": t.timeout_seconds,
        "max_retries": t.retries.max,
        "retry_interval_seconds": t.retries.interval_seconds,
        "overlap_policy": t.overlap_policy,
        "misfire_policy": t.misfire_policy,
        "sequence_position": t.sequence_position,
    }


def _describe(expressions) -> str:
    try:
        return describe(list(expressions))
    except CronError:
        return "agendamento inválido"


MODE_LABELS = {
    ScheduleMode.OWN: "próprio",
    ScheduleMode.INHERIT: "herdado",
    ScheduleMode.MANUAL: "somente manual",
}
_SOURCE_LABELS = {"subcategory": "da subcategoria", "group": "do grupo"}


EXECUTION_LABELS = {ExecutionMode.PARALLEL: "paralela", ExecutionMode.SEQUENTIAL: "sequencial"}


def _execution(doc: ExecutionDoc | None) -> tuple[ExecutionMode, bool]:
    return (doc.mode, doc.stop_on_failure) if doc is not None else (ExecutionMode.PARALLEL, False)


def _sync_execution(sub: Subcategory, doc: ExecutionDoc | None, mode: str) -> list[str]:
    """Like the schedule: missing in the file = keep on merge, back to parallel on overwrite."""
    if doc is None and mode != "overwrite":
        return []
    execution_mode, stop = _execution(doc)
    details = []
    if sub.execution_mode is not execution_mode:
        details.append(
            f"execução: {EXECUTION_LABELS[sub.execution_mode]} → {EXECUTION_LABELS[execution_mode]}"
        )
    if sub.stop_on_failure != stop:
        details.append("parar na falha: " + ("sim" if stop else "não"))
    sub.execution_mode = execution_mode
    sub.stop_on_failure = stop
    return details


def _task_schedule_detail(task: Task) -> str:
    effective = task.effective_schedule
    if effective.source in _SOURCE_LABELS:
        return f"agendamento herdado {_SOURCE_LABELS[effective.source]}: " + _describe(
            effective.expressions
        )
    if effective.source == "none":
        return "herda o agendamento, mas a subcategoria e o grupo não têm um (só execução manual)"
    return _describe(effective.expressions)


def _owner_schedule(doc: ScheduleDoc | None) -> tuple[list[str], str | None]:
    return (list(doc.cron), doc.timezone) if doc is not None else ([], None)


def _sync_owner_schedule(
    owner: Group | Subcategory, doc: ScheduleDoc | None, mode: str
) -> list[str]:
    """Group/subcategory schedule. A file without one clears it on overwrite and keeps
    the current one on merge (files from before inherited schedules never have one)."""
    if doc is None and mode != "overwrite":
        return []
    crons, timezone = _owner_schedule(doc)
    details = []
    if list(owner.cron_expressions) != crons:
        details.append(f"agendamento: {_describe(owner.cron_expressions)} → {_describe(crons)}")
    elif owner.timezone != timezone:
        details.append("fuso do agendamento alterado")
    owner.cron_expressions = crons
    owner.timezone = timezone
    return details


@dataclass
class _VarOutcome:
    details: list[str] = field(default_factory=list)


class _Importer:
    def __init__(
        self,
        session: Session,
        box: SecretBox,
        opts: ImportOptions,
        doc: ExportDoc,
        cipher: ExportCipher | None,
        fallback_timezone: str,
    ) -> None:
        self.s = session
        self.box = box
        self.opts = opts
        self.doc = doc
        self.cipher = cipher
        self.fallback_tz = fallback_timezone
        self.items: list[PlanItem] = []
        self.pending: list[PendingSecret] = []
        self.awaiting_password = False

    # ---------------------------------------------------------------- helpers
    def _item(self, **kw) -> PlanItem:
        item = PlanItem(**kw)
        self.items.append(item)
        return item

    def _resolution(self, path: str) -> Resolution:
        return self.opts.resolutions.get(path) or Resolution(action="skip")

    def _find(self, model, name: str, **parent):
        stmt = select(model).where(func.lower(model.name) == name.lower())
        for column, value in parent.items():
            stmt = stmt.where(getattr(model, column) == value)
        return self.s.scalars(stmt).first()

    def _free_name(self, model, wanted: str | None, base: str, **parent) -> str:
        if wanted:
            name = wanted.strip()
            if not name:
                raise ImportFailure("O novo nome não pode ser vazio.")
            if self._find(model, name, **parent) is not None:
                raise ImportFailure(f"Já existe '{name}'; escolha outro nome para renomear.")
            return name
        for n in range(1, 1000):
            suffix = " (importado)" if n == 1 else f" (importado {n})"
            name = base[: 100 - len(suffix)] + suffix
            if self._find(model, name, **parent) is None:
                return name
        raise ImportFailure(
            f"Não foi possível gerar um nome livre para '{base}'."
        )  # pragma: no cover

    def _task_active(self, t: TaskDoc) -> bool:
        return t.active and self.opts.activate_tasks

    # ---------------------------------------------------------------- variables
    def _secret_plain(self, d: VariableDoc, vpath: str) -> str | None:
        provided = self.opts.secret_values.get(vpath)
        if provided:
            return provided
        if d.value_encrypted is not None:
            if self.cipher is None:
                self.awaiting_password = True
                return None
            return self.cipher.decrypt(d.value_encrypted)
        return d.value

    def _owner_columns(self, scope: VariableScope, owner_id: int | None) -> dict:
        return {
            VariableScope.GLOBAL: {},
            VariableScope.GROUP: {"group_id": owner_id},
            VariableScope.SUBCATEGORY: {"subcategory_id": owner_id},
            VariableScope.TASK: {"task_id": owner_id},
        }[scope]

    def _existing_vars(self, scope: VariableScope, owner_id: int | None) -> dict[str, Variable]:
        stmt = select(Variable).where(Variable.scope == scope)
        for column, value in self._owner_columns(scope, owner_id).items():
            stmt = stmt.where(getattr(Variable, column) == value)
        return {v.key: v for v in self.s.scalars(stmt)}

    def _same_secret(self, existing: Variable, plain: str) -> bool:
        if not existing.is_secret or existing.value is None:
            return False
        try:
            return self.box.decrypt(existing.value) == plain
        except SecretDecryptError:
            return False

    def _var_differs(self, ex: Variable, d: VariableDoc, vpath: str) -> bool:
        if ex.is_secret != d.secret or ex.description != d.description:
            return True
        if not d.secret:
            return ex.value != d.value
        plain = self._secret_plain(d, vpath)
        return plain is not None and not self._same_secret(ex, plain)

    def _sync_vars(
        self,
        scope: VariableScope,
        owner_id: int | None,
        docs: list[VariableDoc],
        path: str,
        owner_label: str,
        mode: Literal["exact", "upsert"],
    ) -> list[str]:
        existing = self._existing_vars(scope, owner_id)
        added, changed, removed, kept = [], [], [], []
        for d in docs:
            vpath = f"{path}/var:{d.key}"
            ex = existing.get(d.key)
            keep_current = False
            if d.secret:
                plain = self._secret_plain(d, vpath)
                if plain is not None:
                    stored = self.box.encrypt(plain)
                elif ex is not None and ex.is_secret and ex.value is not None:
                    stored, keep_current = ex.value, True
                else:
                    stored = None
                if stored is None and not (d.value_encrypted and self.cipher is None):
                    self.pending.append(PendingSecret(path=vpath, key=d.key, owner=owner_label))
            else:
                stored = d.value

            if ex is None:
                self.s.add(
                    Variable(
                        scope=scope,
                        key=d.key,
                        value=stored,
                        is_secret=d.secret,
                        description=d.description,
                        **self._owner_columns(scope, owner_id),
                    )
                )
                added.append(d.key)
                continue
            if keep_current:
                kept.append(d.key)
                differs = ex.is_secret != d.secret or ex.description != d.description
            else:
                differs = self._var_differs(ex, d, vpath)
            if differs:
                changed.append(d.key)
            ex.is_secret = d.secret
            ex.description = d.description
            ex.value = stored

        if mode == "exact":
            file_keys = {d.key for d in docs}
            for key, ex in existing.items():
                if key not in file_keys:
                    self.s.delete(ex)
                    removed.append(key)
        self.s.flush()

        details = []
        if added:
            details.append("variáveis novas: " + ", ".join(added))
        if changed:
            details.append("variáveis alteradas: " + ", ".join(changed))
        if removed:
            details.append("variáveis removidas: " + ", ".join(removed))
        if kept:
            details.append("segredos sem valor no arquivo mantêm o valor atual: " + ", ".join(kept))
        return details

    # ---------------------------------------------------------------- settings / globals
    def import_settings(self) -> None:
        wanted = self.doc.settings.default_timezone if self.doc.settings else None
        if not wanted:
            return
        current = get_default_timezone(self.s, self.fallback_tz)
        base = {"path": "settings", "kind": "settings", "name": "Configurações gerais", "depth": 0}
        if current == wanted:
            self._item(**base, action="unchanged")
        elif self.opts.apply_settings:
            set_setting(self.s, DEFAULT_TIMEZONE, wanted)
            self._item(**base, action="update", details=[f"fuso padrão: {current} → {wanted}"])
        else:
            self._item(
                **base, action="skip", details=[f"fuso padrão do arquivo ({wanted}) ignorado"]
            )

    def import_globals(self) -> None:
        docs = self.doc.variables
        if not docs:
            return
        existing = self._existing_vars(VariableScope.GLOBAL, None)
        conflict = any(
            d.key in existing and self._var_differs(existing[d.key], d, f"globals/var:{d.key}")
            for d in docs
        )
        base = {
            "path": "globals",
            "kind": "globals",
            "name": "Variáveis globais",
            "depth": 0,
            "allowed_resolutions": GLOBAL_RESOLUTIONS,
        }
        # An explicit choice always wins; without one, non-conflicting globals are merged.
        explicit = self.opts.resolutions.get("globals")
        if not conflict and (explicit is None or explicit.action == "merge"):
            details = self._sync_vars(
                VariableScope.GLOBAL, None, docs, "globals", "Global", "upsert"
            )
            self._item(
                **base,
                action="update" if details else "unchanged",
                resolution=explicit.action if explicit else None,
                details=details,
            )
            return
        res = self._resolution("globals")
        if res.action in ("skip", "rename"):
            self._item(
                **base,
                action="skip",
                conflict=conflict,
                resolution="skip",
                details=["variáveis globais não serão alteradas"],
            )
            return
        mode = "exact" if res.action == "overwrite" else "upsert"
        details = self._sync_vars(VariableScope.GLOBAL, None, docs, "globals", "Global", mode)
        self._item(
            **base,
            action="update" if details else "unchanged",
            conflict=conflict,
            resolution=res.action,
            details=details,
        )

    # ---------------------------------------------------------------- tasks
    def create_task(
        self,
        t: TaskDoc,
        sub: Subcategory,
        path: str,
        depth: int,
        name: str | None = None,
        action: str = "create",
    ) -> None:
        task = Task(
            subcategory_id=sub.id,
            name=name or t.name,
            is_active=self._task_active(t),
            **_task_fields(t),
        )
        self.s.add(task)
        self.s.flush()
        details = [_task_schedule_detail(task)]
        if t.active and not task.is_active:
            details.append("entra pausada")
        details += self._sync_vars(
            VariableScope.TASK, task.id, t.variables, path, f"Tarefa {task.name}", "exact"
        )
        self._item(
            path=path,
            kind="task",
            name=t.name,
            depth=depth,
            action=action,
            new_name=name if action == "rename" else None,
            details=details,
        )

    def update_task(
        self, ex: Task, t: TaskDoc, path: str, depth: int, mode: Action, conflict: bool
    ) -> None:
        wanted = {**_task_fields(t), "is_active": self._task_active(t)}
        details = []
        for column, value in wanted.items():
            current = getattr(ex, column)
            if current != value:
                if column == "schedule_mode":
                    details.append(
                        f"origem do agendamento: {MODE_LABELS[current]} → {MODE_LABELS[value]}"
                    )
                elif column == "cron_expressions":
                    label = "agendamento próprio" if value or current else "agendamento"
                    details.append(f"{label}: {_describe(current)} → {_describe(value)}")
                elif column == "is_active":
                    details.append("entra pausada" if not value else "será ativada")
                else:
                    details.append(f"{_TASK_LABELS[column]} alterado")
                setattr(ex, column, value)
        var_mode = "exact" if mode == "overwrite" else "upsert"
        details += self._sync_vars(
            VariableScope.TASK, ex.id, t.variables, path, f"Tarefa {ex.name}", var_mode
        )
        self._item(
            path=path,
            kind="task",
            name=t.name,
            depth=depth,
            action="update" if details else "unchanged",
            conflict=conflict,
            resolution=mode if conflict else None,
            allowed_resolutions=ENTITY_RESOLUTIONS if conflict else [],
            details=details,
        )

    def task_into(
        self, t: TaskDoc, sub: Subcategory, path: str, depth: int, parent_mode: Action | None
    ) -> None:
        ex = self._find(Task, t.name, subcategory_id=sub.id)
        if ex is None:
            self.create_task(t, sub, path, depth)
        elif parent_mode == "overwrite":
            self.update_task(ex, t, path, depth, "overwrite", conflict=False)
        else:
            self._existing_task(ex, t, sub, path, depth)

    def _existing_task(self, ex: Task, t: TaskDoc, sub: Subcategory, path: str, depth: int) -> None:
        res = self._resolution(path)
        if res.action == "skip":
            self._item(
                path=path,
                kind="task",
                name=t.name,
                depth=depth,
                action="skip",
                conflict=True,
                resolution="skip",
                allowed_resolutions=ENTITY_RESOLUTIONS,
                details=["já existe; não será alterada"],
            )
        elif res.action == "rename":
            name = self._free_name(Task, res.new_name, t.name, subcategory_id=sub.id)
            self.create_task(t, sub, path, depth, name=name, action="rename")
            self.items[-1].conflict = True
            self.items[-1].resolution = "rename"
            self.items[-1].allowed_resolutions = ENTITY_RESOLUTIONS
        else:
            self.update_task(ex, t, path, depth, res.action, conflict=True)

    # ---------------------------------------------------------------- subcategories
    def create_subcategory(
        self,
        s: SubcategoryDoc,
        group: Group,
        path: str,
        depth: int,
        name: str | None = None,
        action: str = "create",
    ) -> None:
        crons, timezone = _owner_schedule(s.schedule)
        execution_mode, stop = _execution(s.execution)
        sub = Subcategory(
            group_id=group.id,
            name=name or s.name,
            description=s.description,
            is_active=s.active,
            cron_expressions=crons,
            timezone=timezone,
            execution_mode=execution_mode,
            stop_on_failure=stop,
        )
        self.s.add(sub)
        self.s.flush()
        details = [f"agendamento: {_describe(crons)}"] if crons else []
        if execution_mode is ExecutionMode.SEQUENTIAL:
            details.append("execução sequencial" + (" (para na falha)" if stop else ""))
        details += self._sync_vars(
            VariableScope.SUBCATEGORY,
            sub.id,
            s.variables,
            path,
            f"Subcategoria {sub.name}",
            "exact",
        )
        self._item(
            path=path,
            kind="subcategory",
            name=s.name,
            depth=depth,
            action=action,
            new_name=name if action == "rename" else None,
            details=details,
        )
        for t in s.tasks:
            self.create_task(t, sub, f"{path}/task:{t.name}", depth + 1)

    def update_subcategory(
        self,
        ex: Subcategory,
        s: SubcategoryDoc,
        path: str,
        depth: int,
        mode: Action,
        conflict: bool,
    ) -> None:
        details = []
        if ex.description != s.description:
            ex.description = s.description
            details.append("descrição alterada")
        if ex.is_active != s.active:
            ex.is_active = s.active
            details.append("será ativada" if s.active else "será pausada")
        details += _sync_owner_schedule(ex, s.schedule, mode)
        details += _sync_execution(ex, s.execution, mode)
        details += self._sync_vars(
            VariableScope.SUBCATEGORY,
            ex.id,
            s.variables,
            path,
            f"Subcategoria {ex.name}",
            "exact" if mode == "overwrite" else "upsert",
        )
        item = self._item(
            path=path,
            kind="subcategory",
            name=s.name,
            depth=depth,
            action="update" if details else "unchanged",
            conflict=conflict,
            resolution=mode if conflict else None,
            allowed_resolutions=ENTITY_RESOLUTIONS if conflict else [],
            details=details,
        )
        for t in s.tasks:
            self.task_into(t, ex, f"{path}/task:{t.name}", depth + 1, mode)
        if mode == "overwrite":
            names = {t.name.lower() for t in s.tasks}
            for task in self.s.scalars(select(Task).where(Task.subcategory_id == ex.id)).all():
                if task.name.lower() not in names:
                    self._item(
                        path=f"{path}/task:{task.name}",
                        kind="task",
                        name=task.name,
                        depth=depth + 1,
                        action="delete",
                        details=["não está no arquivo; será excluída com o histórico"],
                    )
                    self.s.delete(task)
            self.s.flush()
        if item.action == "unchanged" and any(
            i.action not in ("unchanged", "skip")
            for i in self.items
            if i.path.startswith(path + "/")
        ):
            item.action = "update"

    def subcategory_into(
        self, s: SubcategoryDoc, group: Group, path: str, depth: int, parent_mode: Action | None
    ) -> None:
        ex = self._find(Subcategory, s.name, group_id=group.id)
        if ex is None:
            self.create_subcategory(s, group, path, depth)
            return
        if parent_mode == "overwrite":
            self.update_subcategory(ex, s, path, depth, "overwrite", conflict=False)
            return
        res = self._resolution(path)
        if res.action == "skip":
            self._item(
                path=path,
                kind="subcategory",
                name=s.name,
                depth=depth,
                action="skip",
                conflict=True,
                resolution="skip",
                allowed_resolutions=ENTITY_RESOLUTIONS,
                details=["já existe; não será alterada"],
            )
        elif res.action == "rename":
            name = self._free_name(Subcategory, res.new_name, s.name, group_id=group.id)
            start = len(self.items)
            self.create_subcategory(s, group, path, depth, name=name, action="rename")
            self.items[start].conflict = True
            self.items[start].resolution = "rename"
            self.items[start].allowed_resolutions = ENTITY_RESOLUTIONS
        else:
            self.update_subcategory(ex, s, path, depth, res.action, conflict=True)

    # ---------------------------------------------------------------- groups
    def create_group(
        self, g: GroupDoc, path: str, name: str | None = None, action: str = "create"
    ) -> None:
        crons, timezone = _owner_schedule(g.schedule)
        group = Group(
            name=name or g.name,
            description=g.description,
            is_active=g.active,
            cron_expressions=crons,
            timezone=timezone,
        )
        self.s.add(group)
        self.s.flush()
        details = [f"agendamento: {_describe(crons)}"] if crons else []
        details += self._sync_vars(
            VariableScope.GROUP, group.id, g.variables, path, f"Grupo {group.name}", "exact"
        )
        self._item(
            path=path,
            kind="group",
            name=g.name,
            depth=0,
            action=action,
            new_name=name if action == "rename" else None,
            details=details,
        )
        for s in g.subcategories:
            self.create_subcategory(s, group, f"{path}/sub:{s.name}", 1)

    def update_group(self, ex: Group, g: GroupDoc, path: str, mode: Action) -> None:
        details = []
        if ex.description != g.description:
            ex.description = g.description
            details.append("descrição alterada")
        if ex.is_active != g.active:
            ex.is_active = g.active
            details.append("será ativado" if g.active else "será pausado")
        details += _sync_owner_schedule(ex, g.schedule, mode)
        details += self._sync_vars(
            VariableScope.GROUP,
            ex.id,
            g.variables,
            path,
            f"Grupo {ex.name}",
            "exact" if mode == "overwrite" else "upsert",
        )
        item = self._item(
            path=path,
            kind="group",
            name=g.name,
            depth=0,
            action="update" if details else "unchanged",
            conflict=True,
            resolution=mode,
            allowed_resolutions=ENTITY_RESOLUTIONS,
            details=details,
        )
        for s in g.subcategories:
            self.subcategory_into(s, ex, f"{path}/sub:{s.name}", 1, mode)
        if mode == "overwrite":
            names = {s.name.lower() for s in g.subcategories}
            subs = self.s.scalars(select(Subcategory).where(Subcategory.group_id == ex.id)).all()
            for sub in subs:
                if sub.name.lower() not in names:
                    n_tasks = self.s.scalar(
                        select(func.count(Task.id)).where(Task.subcategory_id == sub.id)
                    )
                    self._item(
                        path=f"{path}/sub:{sub.name}",
                        kind="subcategory",
                        name=sub.name,
                        depth=1,
                        action="delete",
                        details=[
                            f"não está no arquivo; será excluída com {n_tasks} "
                            "tarefa(s) e histórico"
                        ],
                    )
                    self.s.delete(sub)
            self.s.flush()
        if item.action == "unchanged" and any(
            i.action not in ("unchanged", "skip")
            for i in self.items
            if i.path.startswith(path + "/")
        ):
            item.action = "update"

    def import_group(self, g: GroupDoc) -> None:
        path = f"group:{g.name}"
        if self.doc.scope == "subcategory":
            self._container_group(g, path)
            return
        ex = self._find(Group, g.name)
        if ex is None:
            self.create_group(g, path)
            return
        res = self._resolution(path)
        if res.action == "skip":
            self._item(
                path=path,
                kind="group",
                name=g.name,
                depth=0,
                action="skip",
                conflict=True,
                resolution="skip",
                allowed_resolutions=ENTITY_RESOLUTIONS,
                details=["já existe; nada abaixo dele será importado"],
            )
        elif res.action == "rename":
            name = self._free_name(Group, res.new_name, g.name)
            start = len(self.items)
            self.create_group(g, path, name=name, action="rename")
            self.items[start].conflict = True
            self.items[start].resolution = "rename"
            self.items[start].allowed_resolutions = ENTITY_RESOLUTIONS
        else:
            self.update_group(ex, g, path, res.action)

    def _container_group(self, g: GroupDoc, path: str) -> None:
        """Subcategory exports: the group is only where the subcategory goes."""
        if self.opts.target_group_id is not None:
            group = self.s.get(Group, self.opts.target_group_id)
            if group is None:
                raise ImportFailure(f"Grupo de destino {self.opts.target_group_id} não encontrado.")
        else:
            group = self._find(Group, g.name)
        if group is None:
            group = Group(name=g.name, description=g.description, is_active=g.active)
            self.s.add(group)
            self.s.flush()
            self._item(
                path=path,
                kind="group",
                name=g.name,
                depth=0,
                action="create",
                details=["grupo de destino não existia e será criado"],
            )
        else:
            self._item(
                path=path,
                kind="group",
                name=group.name,
                depth=0,
                action="unchanged",
                details=["grupo de destino"],
            )
        for s in g.subcategories:
            self.subcategory_into(s, group, f"{path}/sub:{s.name}", 1, None)

    # ---------------------------------------------------------------- run
    def run(self) -> None:
        self.import_settings()
        self.import_globals()
        for g in self.doc.groups:
            self.import_group(g)
        bump_config_revision(self.s)
        self.s.flush()


def _header(doc: ExportDoc) -> dict:
    return {
        "schema_version": doc.schema_version,
        "rts_version": doc.rts_version,
        "exported_at": doc.exported_at.isoformat(),
        "scope": doc.scope,
        "secrets_mode": doc.secrets_mode,
        "groups": [g.name for g in doc.groups],
        "has_settings": bool(doc.settings and doc.settings.default_timezone),
    }


def run_import(
    session: Session,
    box: SecretBox,
    opts: ImportOptions,
    *,
    dry_run: bool,
    fallback_timezone: str,
) -> ImportReport:
    try:
        doc = parse_document(opts.content)
    except FileError as exc:
        return ImportReport(valid=False, errors=exc.errors)

    report = ImportReport(valid=True, header=_header(doc), tasks_paused=not opts.activate_tasks)
    needs_password = doc.secrets_mode == "encrypted" and any(
        v.value_encrypted is not None for v in doc.iter_variables()
    )
    report.needs_password = needs_password
    cipher = None
    if needs_password and opts.password:
        enc = doc.encryption
        try:
            cipher = ExportCipher.open(opts.password, enc.salt, enc.iterations, enc.check)
            report.password_ok = True
        except WrongPasswordError:
            report.password_ok = False
            report.valid = False
            report.errors = ["Senha incorreta."]
            return report
    if needs_password and cipher is None and not dry_run:
        report.valid = False
        report.errors = ["Informe a senha usada na exportação para importar os segredos cifrados."]
        return report

    importer = _Importer(session, box, opts, doc, cipher, fallback_timezone)
    try:
        importer.run()
    except (ImportFailure, ValueError) as exc:
        session.rollback()
        report.valid = False
        report.errors = [str(exc)]
        return report
    except Exception:
        session.rollback()
        raise

    report.items = importer.items
    report.pending_secrets = importer.pending
    counts = {"create": 0, "update": 0, "delete": 0, "skip": 0, "unchanged": 0}
    for item in importer.items:
        counts["create" if item.action == "rename" else item.action] += 1
    report.summary = counts

    if dry_run:
        session.rollback()
    else:
        session.commit()
        report.applied = True
    return report

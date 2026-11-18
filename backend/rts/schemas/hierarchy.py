"""Request/response models for groups, subcategories and tasks."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from rts.models.enums import MisfirePolicy, OverlapPolicy, ScheduleMode, Shell
from rts.models.hierarchy import ScheduleSource
from rts.scheduling.cron import MAX_EXPRESSIONS, CronError, get_timezone, normalize_expression
from rts.schemas.common import DescriptionStr, NameStr, ORMModel

MAX_TIMEOUT_SECONDS = 7 * 24 * 3600


def _normalize_crons(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if len(value) > MAX_EXPRESSIONS:
        raise ValueError(f"Máximo de {MAX_EXPRESSIONS} expressões por agendamento.")
    normalized: list[str] = []
    for expr in value:
        try:
            canon = normalize_expression(expr)
        except CronError as exc:
            raise ValueError(f"'{expr}': {exc}") from exc
        if canon not in normalized:
            normalized.append(canon)
    return normalized


def _validate_tz(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    try:
        get_timezone(value)
    except CronError as exc:
        raise ValueError(str(exc)) from exc
    return value


class _ScheduleFields(BaseModel):
    """Validation shared by everything that carries a schedule."""

    @field_validator("cron_expressions", check_fields=False)
    @classmethod
    def _crons(cls, v):
        return _normalize_crons(v)

    @field_validator("timezone", check_fields=False)
    @classmethod
    def _tz(cls, v):
        return _validate_tz(v)


class ScheduleOwnerOut(ORMModel):
    cron_expressions: list[str]
    timezone: str | None
    schedule_description: str


# --------------------------------------------------------------------------- groups
class GroupCreate(_ScheduleFields):
    name: NameStr
    description: DescriptionStr = ""
    is_active: bool = True
    cron_expressions: list[str] = Field(
        default_factory=list, description="Agendamento herdado pelas tarefas (vazio = nenhum)."
    )
    timezone: str | None = None


class GroupUpdate(_ScheduleFields):
    name: NameStr | None = None
    description: DescriptionStr | None = None
    is_active: bool | None = None
    cron_expressions: list[str] | None = None
    timezone: str | None = None


class GroupOut(ScheduleOwnerOut):
    id: int
    name: str
    description: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- subcategories
class SubcategoryCreate(_ScheduleFields):
    group_id: int
    name: NameStr
    description: DescriptionStr = ""
    is_active: bool = True
    cron_expressions: list[str] = Field(
        default_factory=list,
        description="Agendamento herdado pelas tarefas (vazio = usa o do grupo).",
    )
    timezone: str | None = None


class SubcategoryUpdate(_ScheduleFields):
    group_id: int | None = None
    name: NameStr | None = None
    description: DescriptionStr | None = None
    is_active: bool | None = None
    cron_expressions: list[str] | None = None
    timezone: str | None = None


class InheritedScheduleOut(BaseModel):
    """What tasks set to "inherit" in a subcategory follow."""

    source: ScheduleSource
    cron_expressions: list[str]
    timezone: str | None
    description: str


class SubcategoryOut(ScheduleOwnerOut):
    id: int
    group_id: int
    name: str
    description: str
    is_active: bool
    is_effectively_active: bool
    inherited_schedule: InheritedScheduleOut
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- tasks
CommandStr = Annotated[str, StringConstraints(min_length=1, max_length=100_000)]


def _validate_command(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("O comando não pode ser vazio.")
    return value


class _TaskFields(_ScheduleFields):
    @field_validator("command", check_fields=False)
    @classmethod
    def _cmd(cls, v):
        return _validate_command(v)

    @field_validator("working_dir", check_fields=False)
    @classmethod
    def _wd(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v


class TaskCreate(_TaskFields):
    subcategory_id: int
    name: NameStr
    description: DescriptionStr = ""
    command: CommandStr
    shell: Shell | None = None
    working_dir: Annotated[str, StringConstraints(max_length=1024)] | None = None
    schedule_mode: ScheduleMode | None = Field(
        default=None,
        description="own (agendamento próprio), inherit (da subcategoria/grupo) ou manual. "
        "Sem valor: own se houver expressões cron, senão manual.",
    )
    cron_expressions: list[str] = Field(default_factory=list)
    timezone: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=MAX_TIMEOUT_SECONDS)
    max_retries: int = Field(default=0, ge=0, le=100)
    retry_interval_seconds: int = Field(default=60, ge=0, le=86_400)
    overlap_policy: OverlapPolicy = OverlapPolicy.SKIP
    misfire_policy: MisfirePolicy = MisfirePolicy.IGNORE
    is_active: bool = True


class TaskUpdate(_TaskFields):
    """Partial update. Send ``null`` explicitly to clear nullable fields."""

    subcategory_id: int | None = None
    name: NameStr | None = None
    description: DescriptionStr | None = None
    command: CommandStr | None = None
    shell: Shell | None = None
    working_dir: Annotated[str, StringConstraints(max_length=1024)] | None = None
    schedule_mode: ScheduleMode | None = None
    cron_expressions: list[str] | None = None
    timezone: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=MAX_TIMEOUT_SECONDS)
    max_retries: int | None = Field(default=None, ge=0, le=100)
    retry_interval_seconds: int | None = Field(default=None, ge=0, le=86_400)
    overlap_policy: OverlapPolicy | None = None
    misfire_policy: MisfirePolicy | None = None
    is_active: bool | None = None


class TaskOut(ORMModel):
    id: int
    subcategory_id: int
    group_id: int
    name: str
    description: str
    command: str
    shell: Shell | None
    working_dir: str | None
    schedule_mode: ScheduleMode
    cron_expressions: list[str] = Field(description="Agendamento próprio da tarefa.")
    timezone: str | None = Field(description="Fuso do agendamento próprio.")
    schedule_source: ScheduleSource = Field(
        description="De onde vem o agendamento efetivo: task, subcategory, group, manual ou "
        "none (herda, mas nem a subcategoria nem o grupo têm agendamento)."
    )
    effective_cron_expressions: list[str]
    schedule_description: str = Field(description="Descrição do agendamento efetivo.")
    effective_timezone: str
    timeout_seconds: int | None
    max_retries: int
    retry_interval_seconds: int
    overlap_policy: OverlapPolicy
    misfire_policy: MisfirePolicy
    is_active: bool
    is_effectively_active: bool
    next_run_at: datetime | None
    created_at: datetime
    updated_at: datetime

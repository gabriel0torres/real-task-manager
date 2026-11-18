"""Request/response models for groups, subcategories and tasks."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from rts.models.enums import MisfirePolicy, OverlapPolicy, Shell
from rts.scheduling.cron import MAX_EXPRESSIONS, CronError, get_timezone, normalize_expression
from rts.schemas.common import DescriptionStr, NameStr, ORMModel

MAX_TIMEOUT_SECONDS = 7 * 24 * 3600


# --------------------------------------------------------------------------- groups
class GroupCreate(BaseModel):
    name: NameStr
    description: DescriptionStr = ""
    is_active: bool = True


class GroupUpdate(BaseModel):
    name: NameStr | None = None
    description: DescriptionStr | None = None
    is_active: bool | None = None


class GroupOut(ORMModel):
    id: int
    name: str
    description: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- subcategories
class SubcategoryCreate(BaseModel):
    group_id: int
    name: NameStr
    description: DescriptionStr = ""
    is_active: bool = True


class SubcategoryUpdate(BaseModel):
    group_id: int | None = None
    name: NameStr | None = None
    description: DescriptionStr | None = None
    is_active: bool | None = None


class SubcategoryOut(ORMModel):
    id: int
    group_id: int
    name: str
    description: str
    is_active: bool
    is_effectively_active: bool
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- tasks
CommandStr = Annotated[str, StringConstraints(min_length=1, max_length=100_000)]


def _normalize_crons(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if len(value) > MAX_EXPRESSIONS:
        raise ValueError(f"Máximo de {MAX_EXPRESSIONS} expressões por tarefa.")
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


def _validate_command(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("O comando não pode ser vazio.")
    return value


class _TaskFields(BaseModel):
    @field_validator("cron_expressions", check_fields=False)
    @classmethod
    def _crons(cls, v):
        return _normalize_crons(v)

    @field_validator("timezone", check_fields=False)
    @classmethod
    def _tz(cls, v):
        return _validate_tz(v)

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
    cron_expressions: list[str]
    schedule_description: str
    timezone: str | None
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

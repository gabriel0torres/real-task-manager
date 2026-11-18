"""Schedule preview, system info, general settings (incl. retention) and health check."""

from __future__ import annotations

import sys
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from rts import __version__
from rts.api.deps import SessionDep, SettingsDep
from rts.engine.process import default_shell
from rts.models.base import utcnow
from rts.scheduling.cron import CronError, get_timezone, next_fire_times, normalize_expression
from rts.scheduling.describe import describe
from rts.services.retention import (
    RETENTION_DAYS,
    RETENTION_KEEP_LAST,
    apply_retention,
    get_retention,
)
from rts.services.settings import (
    DEFAULT_TIMEZONE,
    bump_config_revision,
    get_default_timezone,
    set_setting,
)

# Read-only helpers (any logged-in user with "view").
router = APIRouter()
# Settings (writes need "manage_settings").
settings_router = APIRouter(tags=["Configurações"])
# No authentication.
public_router = APIRouter()


# --------------------------------------------------------------------------- schedule preview
class SchedulePreviewIn(BaseModel):
    cron_expressions: list[str]
    timezone: str | None = Field(default=None, description="Omitir para usar o fuso padrão.")
    count: int = Field(default=5, ge=1, le=50)


class SchedulePreviewOut(BaseModel):
    valid: bool
    error: str | None = None
    description: str | None = Field(default=None, description="Descrição em português.")
    cron_expressions: list[str] = Field(description="Expressões normalizadas.")
    timezone: str
    next_runs: list[datetime]


@router.post(
    "/schedule/preview",
    response_model=SchedulePreviewOut,
    tags=["Agendamento"],
    summary="Validar expressões cron e prever as próximas execuções",
)
def schedule_preview(data: SchedulePreviewIn, session: SessionDep, settings: SettingsDep):
    tz = data.timezone or get_default_timezone(session, settings.default_timezone)
    try:
        normalized = [normalize_expression(e) for e in data.cron_expressions]
        runs = next_fire_times(normalized, tz, data.count)
    except CronError as exc:
        return SchedulePreviewOut(
            valid=False,
            error=str(exc),
            cron_expressions=data.cron_expressions,
            timezone=tz,
            next_runs=[],
        )
    return SchedulePreviewOut(
        valid=True,
        description=describe(normalized),
        cron_expressions=normalized,
        timezone=tz,
        next_runs=runs,
    )


# --------------------------------------------------------------------------- system info
class SystemInfoOut(BaseModel):
    version: str
    platform: str = Field(description="windows | linux | darwin")
    default_shell: str = Field(description="Shell usado quando a tarefa não define um.")
    metadata_variables: dict[str, str] = Field(
        description="Variáveis RTS_* que o RTS injeta em toda execução, com descrição."
    )


METADATA_VARIABLES = {
    "RTS_RUN_ID": "Número da execução",
    "RTS_TASK_ID": "ID da tarefa",
    "RTS_TASK": "Nome da tarefa",
    "RTS_SUBCATEGORY": "Nome da subcategoria",
    "RTS_GROUP": "Nome do grupo",
    "RTS_ATTEMPT": "Número da tentativa (1, 2, ...)",
    "RTS_TRIGGER": "Gatilho: scheduled, manual, retry ou api",
    "RTS_SCHEDULED_FOR": "Horário agendado (ISO 8601) ou vazio",
}


@router.get(
    "/system/info",
    response_model=SystemInfoOut,
    tags=["Sistema"],
    summary="Informações do servidor",
)
def system_info():
    platform = {"win32": "windows", "darwin": "darwin"}.get(sys.platform, "linux")
    return SystemInfoOut(
        version=__version__,
        platform=platform,
        default_shell=default_shell().value,
        metadata_variables=METADATA_VARIABLES,
    )


# --------------------------------------------------------------------------- settings
class GeneralSettingsOut(BaseModel):
    default_timezone: str
    retention_days: int | None = Field(
        description="Apagar execuções com mais de N dias (nulo = não apagar por idade)."
    )
    retention_keep_last: int | None = Field(
        description="Manter só as N execuções mais recentes por tarefa (nulo = sem limite)."
    )


class GeneralSettingsUpdate(BaseModel):
    default_timezone: str | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    retention_keep_last: int | None = Field(default=None, ge=1, le=100_000)

    @field_validator("default_timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                get_timezone(v)
            except CronError as exc:
                raise ValueError(str(exc)) from exc
        return v


@settings_router.get("/settings", response_model=GeneralSettingsOut, summary="Configurações gerais")
def get_settings(session: SessionDep, settings: SettingsDep):
    days, keep = get_retention(session)
    return GeneralSettingsOut(
        default_timezone=get_default_timezone(session, settings.default_timezone),
        retention_days=days,
        retention_keep_last=keep,
    )


@settings_router.patch(
    "/settings",
    response_model=GeneralSettingsOut,
    summary="Atualizar configurações gerais",
    description="Envie `null` em um campo de retenção para desativá-lo.",
)
def update_settings(data: GeneralSettingsUpdate, session: SessionDep, settings: SettingsDep):
    changes = data.model_dump(exclude_unset=True)
    if changes.get("default_timezone") is not None:
        set_setting(session, DEFAULT_TIMEZONE, changes["default_timezone"])
        bump_config_revision(session)
    if "retention_days" in changes:
        set_setting(session, RETENTION_DAYS, changes["retention_days"])
    if "retention_keep_last" in changes:
        set_setting(session, RETENTION_KEEP_LAST, changes["retention_keep_last"])
    session.commit()
    return get_settings(session, settings)


class RetentionResult(BaseModel):
    deleted: int


@settings_router.post(
    "/settings/retention/apply",
    response_model=RetentionResult,
    summary="Aplicar a retenção de logs agora",
    description="O motor de agendamento também aplica a retenção automaticamente a cada hora.",
)
def run_retention(session: SessionDep):
    return RetentionResult(deleted=apply_retention(session, utcnow()))


# --------------------------------------------------------------------------- health
class HealthOut(BaseModel):
    status: str
    version: str


@public_router.get(
    "/health", response_model=HealthOut, tags=["Sistema"], summary="Verificação de saúde"
)
def health():
    return HealthOut(status="ok", version=__version__)

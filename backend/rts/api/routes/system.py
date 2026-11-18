"""Schedule preview, general settings and health check."""

from __future__ import annotations

import sys
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from rts import __version__
from rts.api.deps import SessionDep, SettingsDep
from rts.engine.process import default_shell
from rts.scheduling.cron import CronError, get_timezone, next_fire_times, normalize_expression
from rts.scheduling.describe import describe
from rts.services.settings import (
    DEFAULT_TIMEZONE,
    bump_config_revision,
    get_default_timezone,
    set_setting,
)

router = APIRouter()


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


# --------------------------------------------------------------------------- settings
class GeneralSettingsOut(BaseModel):
    default_timezone: str


class GeneralSettingsUpdate(BaseModel):
    default_timezone: str | None = None

    @field_validator("default_timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                get_timezone(v)
            except CronError as exc:
                raise ValueError(str(exc)) from exc
        return v


@router.get(
    "/settings",
    response_model=GeneralSettingsOut,
    tags=["Configurações"],
    summary="Configurações gerais",
)
def get_settings(session: SessionDep, settings: SettingsDep):
    return GeneralSettingsOut(
        default_timezone=get_default_timezone(session, settings.default_timezone)
    )


@router.patch(
    "/settings",
    response_model=GeneralSettingsOut,
    tags=["Configurações"],
    summary="Atualizar configurações gerais",
)
def update_settings(data: GeneralSettingsUpdate, session: SessionDep, settings: SettingsDep):
    if data.default_timezone is not None:
        set_setting(session, DEFAULT_TIMEZONE, data.default_timezone)
        bump_config_revision(session)
        session.commit()
    return get_settings(session, settings)


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


# --------------------------------------------------------------------------- health
class HealthOut(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthOut, tags=["Sistema"], summary="Verificação de saúde")
def health():
    return HealthOut(status="ok", version=__version__)

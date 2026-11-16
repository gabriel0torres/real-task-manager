"""Request/response models for variables."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from rts.models.enums import VariableScope
from rts.schemas.common import DescriptionStr

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RESERVED_PREFIX = "RTS_"
MAX_VALUE_LENGTH = 65_536

ValueStr = Annotated[str, StringConstraints(max_length=MAX_VALUE_LENGTH)]


def validate_key(value: str) -> str:
    value = value.strip()
    if not KEY_RE.match(value):
        raise ValueError(
            "Chave inválida: use letras, números e '_' e não comece com número (ex.: API_URL)."
        )
    if len(value) > 128:
        raise ValueError("Chave muito longa (máximo 128 caracteres).")
    if value.upper().startswith(RESERVED_PREFIX):
        raise ValueError(f"O prefixo '{RESERVED_PREFIX}' é reservado para variáveis do sistema.")
    return value


class VariableCreate(BaseModel):
    scope: VariableScope
    owner_id: int | None = Field(
        default=None, description="ID do grupo/subcategoria/tarefa. Omitir para escopo global."
    )
    key: str
    value: ValueStr
    is_secret: bool = False
    description: DescriptionStr = ""

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        return validate_key(v)


class VariableUpdate(BaseModel):
    key: str | None = None
    value: ValueStr | None = Field(
        default=None, description="Novo valor. Omitir para manter o atual (útil para segredos)."
    )
    is_secret: bool | None = None
    description: DescriptionStr | None = None

    @field_validator("key")
    @classmethod
    def _key(cls, v: str | None) -> str | None:
        return None if v is None else validate_key(v)


class VariableOut(BaseModel):
    id: int
    scope: VariableScope
    owner_id: int | None
    key: str
    value: str | None = Field(description="Sempre nulo para segredos.")
    is_secret: bool
    has_value: bool
    description: str
    created_at: datetime
    updated_at: datetime


class VariableSource(BaseModel):
    scope: VariableScope
    owner_id: int | None
    owner_name: str | None
    variable_id: int


class EffectiveVariableOut(BaseModel):
    key: str
    value: str | None = Field(description="Nulo para segredos ou valores pendentes.")
    is_secret: bool
    has_value: bool
    source: VariableSource
    overrides: list[VariableSource] = Field(
        description="Definições em níveis mais gerais que foram sobrescritas."
    )

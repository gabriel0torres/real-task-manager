"""The export file format (schema_version 1).

Layout::

    schema_version: 1
    rts_version: 0.1.0
    exported_at: 2026-11-17T12:00:00Z
    scope: system | group | subcategory
    secrets_mode: omit | encrypted
    encryption: {algorithm, iterations, salt, check}    # only when encrypted
    settings: {default_timezone}                         # only for system exports
    variables: [...]                                     # global variables (system only)
    groups:
      - name, description, active, variables
        subcategories:
          - name, description, active, variables
            tasks:
              - name, description, command, shell, working_dir, active,
                schedule: {cron: [...], timezone, description}
                timeout_seconds, retries: {max, interval_seconds},
                overlap_policy, misfire_policy, variables

Variable: {key, value | value_encrypted, secret, description}. A secret exported
without value has ``value: null`` ("a preencher").

For a ``subcategory`` export the single group is only a container: it carries
the group name (to find/create it on import) but no group variables.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from rts.models.enums import MisfirePolicy, OverlapPolicy, Shell
from rts.schemas.common import NameStr
from rts.schemas.hierarchy import MAX_TIMEOUT_SECONDS, _normalize_crons, _validate_tz
from rts.schemas.variables import MAX_VALUE_LENGTH, validate_key

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 5_000_000

Scope = Literal["system", "group", "subcategory"]
SecretsMode = Literal["omit", "encrypted"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VariableDoc(_Strict):
    key: str
    value: str | None = Field(default=None, max_length=MAX_VALUE_LENGTH)
    value_encrypted: str | None = None
    secret: bool = False
    description: str = ""

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        return validate_key(v)

    @model_validator(mode="after")
    def _check_value(self):
        if not self.secret:
            if self.value is None:
                raise ValueError(f"variável '{self.key}': informe 'value'")
            if self.value_encrypted is not None:
                raise ValueError(f"variável '{self.key}': 'value_encrypted' só vale para segredos")
        elif self.value is not None and self.value_encrypted is not None:
            raise ValueError(f"variável '{self.key}': use 'value' ou 'value_encrypted', não ambos")
        return self


class ScheduleDoc(_Strict):
    cron: list[str] = Field(default_factory=list)
    timezone: str | None = None
    description: str | None = None  # informative only; ignored on import

    @field_validator("cron")
    @classmethod
    def _cron(cls, v: list[str]) -> list[str]:
        return _normalize_crons(v) or []

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return _validate_tz(v)


class RetriesDoc(_Strict):
    max: int = Field(default=0, ge=0, le=100)
    interval_seconds: int = Field(default=60, ge=0, le=86_400)


def _unique(names: list[str], what: str) -> None:
    seen: set[str] = set()
    for name in names:
        low = name.lower()
        if low in seen:
            raise ValueError(f"{what} '{name}' aparece mais de uma vez")
        seen.add(low)


class _WithVariables(_Strict):
    variables: list[VariableDoc] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_keys(self):
        keys = [v.key for v in self.variables]
        if len(keys) != len(set(keys)):
            dup = next(k for k in keys if keys.count(k) > 1)
            raise ValueError(f"variável '{dup}' aparece mais de uma vez")
        return self


class TaskDoc(_WithVariables):
    name: NameStr
    description: str = ""
    command: str = Field(min_length=1, max_length=100_000)
    shell: Shell | None = None
    working_dir: str | None = None
    active: bool = True
    schedule: ScheduleDoc = Field(default_factory=ScheduleDoc)
    timeout_seconds: int | None = Field(default=None, ge=1, le=MAX_TIMEOUT_SECONDS)
    retries: RetriesDoc = Field(default_factory=RetriesDoc)
    overlap_policy: OverlapPolicy = OverlapPolicy.SKIP
    misfire_policy: MisfirePolicy = MisfirePolicy.IGNORE

    @field_validator("command")
    @classmethod
    def _command(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("o comando não pode ser vazio")
        return v


class SubcategoryDoc(_WithVariables):
    name: NameStr
    description: str = ""
    active: bool = True
    tasks: list[TaskDoc] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_tasks(self):
        _unique([t.name for t in self.tasks], "tarefa")
        return self


class GroupDoc(_WithVariables):
    name: NameStr
    description: str = ""
    active: bool = True
    subcategories: list[SubcategoryDoc] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_subs(self):
        _unique([s.name for s in self.subcategories], "subcategoria")
        return self


class EncryptionDoc(_Strict):
    algorithm: Literal["fernet-pbkdf2-sha256"]
    iterations: int = Field(ge=10_000, le=10_000_000)
    salt: str
    check: str


class SettingsDoc(_Strict):
    default_timezone: str | None = None

    @field_validator("default_timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return _validate_tz(v)


class ExportDoc(_WithVariables):
    schema_version: int
    rts_version: str
    exported_at: datetime
    scope: Scope
    secrets_mode: SecretsMode
    encryption: EncryptionDoc | None = None
    settings: SettingsDoc | None = None
    groups: list[GroupDoc] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistency(self):
        if self.secrets_mode == "encrypted" and self.encryption is None:
            raise ValueError("secrets_mode 'encrypted' exige o bloco 'encryption'")
        if self.secrets_mode == "omit":
            for var in self.iter_variables():
                if var.value_encrypted is not None:
                    raise ValueError(
                        f"variável '{var.key}' cifrada em um arquivo com secrets_mode 'omit'"
                    )
        if self.scope != "system" and (self.variables or self.settings):
            raise ValueError("variáveis globais e configurações só existem em exportações 'system'")
        if self.scope in ("group", "subcategory") and len(self.groups) != 1:
            raise ValueError(f"exportação '{self.scope}' deve conter exatamente 1 grupo")
        if self.scope == "subcategory":
            group = self.groups[0]
            if len(group.subcategories) != 1:
                raise ValueError("exportação 'subcategory' deve conter exatamente 1 subcategoria")
            if group.variables:
                raise ValueError("exportação 'subcategory' não inclui variáveis do grupo")
        _unique([g.name for g in self.groups], "grupo")
        return self

    def iter_variables(self):
        yield from self.variables
        for g in self.groups:
            yield from g.variables
            for s in g.subcategories:
                yield from s.variables
                for t in s.tasks:
                    yield from t.variables


class FileError(ValueError):
    """Invalid export file; ``errors`` are user-facing pt-BR messages."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _loc(loc: tuple[Any, ...], raw: dict) -> str:
    """Readable location: groups[financeiro].subcategories[relatórios]..."""
    parts: list[str] = []
    node: Any = raw
    for item in loc:
        if isinstance(item, int):
            try:
                node = node[item]
                label = node.get("name") or node.get("key") if isinstance(node, dict) else None
            except (IndexError, KeyError, TypeError):
                label = None
            parts[-1] = f"{parts[-1]}[{label or item}]" if parts else f"[{item}]"
        else:
            parts.append(str(item))
            node = node.get(item) if isinstance(node, dict) else None
    return ".".join(parts)


_PT_MESSAGES = {
    "extra_forbidden": "campo desconhecido",
    "missing": "campo obrigatório ausente",
    "string_type": "deve ser um texto",
    "int_type": "deve ser um número inteiro",
    "int_parsing": "deve ser um número inteiro",
    "bool_type": "deve ser true ou false",
    "bool_parsing": "deve ser true ou false",
    "list_type": "deve ser uma lista",
    "dict_type": "deve ser um objeto",
    "model_type": "deve ser um objeto",
    "enum": "valor não permitido",
    "literal_error": "valor não permitido",
    "string_too_short": "não pode ser vazio",
    "string_too_long": "texto longo demais",
    "greater_than_equal": "valor abaixo do mínimo permitido",
    "less_than_equal": "valor acima do máximo permitido",
    "datetime_parsing": "data/hora inválida",
    "datetime_type": "data/hora inválida",
}


def parse_document(content: str) -> ExportDoc:
    """Parse and fully validate an export file. Raises FileError."""
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise FileError([f"Arquivo maior que o limite de {MAX_FILE_BYTES // 1_000_000} MB."])
    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (linha {mark.line + 1}, coluna {mark.column + 1})" if mark else ""
        raise FileError([f"YAML inválido{where}: {getattr(exc, 'problem', exc)}"]) from exc
    if not isinstance(raw, dict):
        raise FileError(["O arquivo não é uma exportação do RTS."])

    version = raw.get("schema_version")
    if not isinstance(version, int):
        raise FileError(
            ["Campo 'schema_version' ausente ou inválido: não é uma exportação do RTS."]
        )
    if version > SCHEMA_VERSION:
        raise FileError(
            [
                f"O arquivo usa schema_version {version}, mas esta instalação suporta até "
                f"{SCHEMA_VERSION}. Atualize o RTS para importá-lo."
            ]
        )
    if version < 1:
        raise FileError([f"schema_version {version} não é suportado."])

    try:
        return ExportDoc.model_validate(raw)
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            msg = _PT_MESSAGES.get(err["type"]) or err["msg"].removeprefix("Value error, ")
            where = _loc(err["loc"], raw)
            errors.append(f"{where}: {msg}" if where else msg)
        raise FileError(errors) from exc


# --------------------------------------------------------------------------- YAML output
class _Dumper(yaml.SafeDumper):
    pass


def _str_representer(dumper: yaml.SafeDumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_representer)


def dump_document(data: dict, header_comment: str) -> str:
    body = yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100, indent=2)
    comment = "".join(f"# {line}\n" if line else "#\n" for line in header_comment.splitlines())
    return comment + body

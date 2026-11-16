"""Variables CRUD, secret handling and inheritance resolution.

Resolution order is Global -> Group -> Subcategory -> Task; the most specific
level wins. Secret values are stored as Fernet tokens and are only decrypted
when building the environment of a task process.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from rts.models import Group, Subcategory, Task, Variable, VariableScope
from rts.models.enums import SCOPE_PRECEDENCE
from rts.schemas.variables import (
    EffectiveVariableOut,
    VariableCreate,
    VariableOut,
    VariableSource,
    VariableUpdate,
)
from rts.security.crypto import SecretBox
from rts.services.errors import ConflictError, InvalidInputError, NotFoundError
from rts.services.hierarchy import get_group, get_subcategory, get_task

_OWNER_COLUMN = {
    VariableScope.GROUP: "group_id",
    VariableScope.SUBCATEGORY: "subcategory_id",
    VariableScope.TASK: "task_id",
}


def _owner_kwargs(session: Session, scope: VariableScope, owner_id: int | None) -> dict:
    if scope is VariableScope.GLOBAL:
        if owner_id is not None:
            raise InvalidInputError("Variáveis globais não têm 'owner_id'.")
        return {}
    if owner_id is None:
        raise InvalidInputError(f"Informe 'owner_id' para o escopo '{scope.value}'.")
    {
        VariableScope.GROUP: get_group,
        VariableScope.SUBCATEGORY: get_subcategory,
        VariableScope.TASK: get_task,
    }[scope](session, owner_id)
    return {_OWNER_COLUMN[scope]: owner_id}


def _scope_filter(scope: VariableScope, owner_id: int | None):
    conds = [Variable.scope == scope]
    if scope is not VariableScope.GLOBAL:
        conds.append(getattr(Variable, _OWNER_COLUMN[scope]) == owner_id)
    return conds


def _ensure_key_free(
    session: Session, scope: VariableScope, owner_id: int | None, key: str, exclude_id=None
) -> None:
    stmt = select(Variable.id).where(*_scope_filter(scope, owner_id), Variable.key == key)
    if exclude_id is not None:
        stmt = stmt.where(Variable.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ConflictError(f"A variável '{key}' já existe neste nível.")


def to_out(var: Variable) -> VariableOut:
    return VariableOut(
        id=var.id,
        scope=var.scope,
        owner_id=var.owner_id,
        key=var.key,
        value=None if var.is_secret else var.value,
        is_secret=var.is_secret,
        has_value=var.value is not None,
        description=var.description,
        created_at=var.created_at,
        updated_at=var.updated_at,
    )


def list_variables(
    session: Session, scope: VariableScope | None = None, owner_id: int | None = None
) -> list[Variable]:
    stmt = select(Variable)
    if scope is not None:
        stmt = stmt.where(*_scope_filter(scope, owner_id))
    return list(session.scalars(stmt.order_by(Variable.scope, Variable.key)))


def get_variable(session: Session, variable_id: int) -> Variable:
    var = session.get(Variable, variable_id)
    if var is None:
        raise NotFoundError(f"Variável {variable_id} não encontrada.")
    return var


def create_variable(session: Session, box: SecretBox, data: VariableCreate) -> Variable:
    owner = _owner_kwargs(session, data.scope, data.owner_id)
    _ensure_key_free(session, data.scope, data.owner_id, data.key)
    var = Variable(
        scope=data.scope,
        key=data.key,
        value=box.encrypt(data.value) if data.is_secret else data.value,
        is_secret=data.is_secret,
        description=data.description,
        **owner,
    )
    session.add(var)
    session.flush()
    return var


def update_variable(
    session: Session, box: SecretBox, variable_id: int, data: VariableUpdate
) -> Variable:
    var = get_variable(session, variable_id)
    changes = data.model_dump(exclude_unset=True)

    if changes.get("key") is not None and changes["key"] != var.key:
        _ensure_key_free(session, var.scope, var.owner_id, changes["key"], exclude_id=var.id)
        var.key = changes["key"]
    if changes.get("description") is not None:
        var.description = changes["description"]

    new_secret = changes.get("is_secret")
    new_secret = var.is_secret if new_secret is None else new_secret
    new_value = changes.get("value")

    if var.is_secret and not new_secret and new_value is None:
        raise InvalidInputError(
            "Para deixar de ser secreta, informe um novo valor "
            "(o valor atual não pode ser revelado)."
        )

    if new_value is not None:
        var.value = box.encrypt(new_value) if new_secret else new_value
    elif new_secret and not var.is_secret and var.value is not None:
        var.value = box.encrypt(var.value)
    var.is_secret = new_secret

    session.flush()
    return var


def delete_variable(session: Session, variable_id: int) -> None:
    session.delete(get_variable(session, variable_id))
    session.flush()


# --------------------------------------------------------------------------- inheritance
@dataclass
class ResolvedVariable:
    key: str
    variable: Variable
    owner_name: str | None
    overridden: list[tuple[Variable, str | None]] = field(default_factory=list)


def _chain(session: Session, task: Task) -> list[tuple[VariableScope, int | None, str | None]]:
    sub: Subcategory = task.subcategory
    group: Group = sub.group
    return [
        (VariableScope.GLOBAL, None, None),
        (VariableScope.GROUP, group.id, group.name),
        (VariableScope.SUBCATEGORY, sub.id, sub.name),
        (VariableScope.TASK, task.id, task.name),
    ]


def resolve(session: Session, task: Task) -> list[ResolvedVariable]:
    """Resolve the effective variables of a task, most specific level winning."""
    chain = _chain(session, task)
    assert [c[0] for c in chain] == list(SCOPE_PRECEDENCE)
    resolved: dict[str, ResolvedVariable] = {}
    for scope, owner_id, owner_name in chain:
        for var in session.scalars(select(Variable).where(*_scope_filter(scope, owner_id))):
            previous = resolved.get(var.key)
            entry = ResolvedVariable(var.key, var, owner_name)
            if previous is not None:
                entry.overridden = [*previous.overridden, (previous.variable, previous.owner_name)]
            resolved[var.key] = entry
    return [resolved[k] for k in sorted(resolved)]


def _source(var: Variable, owner_name: str | None) -> VariableSource:
    return VariableSource(
        scope=var.scope, owner_id=var.owner_id, owner_name=owner_name, variable_id=var.id
    )


def effective_variables(session: Session, task: Task) -> list[EffectiveVariableOut]:
    return [
        EffectiveVariableOut(
            key=r.key,
            value=None if r.variable.is_secret else r.variable.value,
            is_secret=r.variable.is_secret,
            has_value=r.variable.value is not None,
            source=_source(r.variable, r.owner_name),
            overrides=[_source(v, n) for v, n in reversed(r.overridden)],
        )
        for r in resolve(session, task)
    ]


@dataclass
class TaskEnvironment:
    env: dict[str, str]
    secret_values: list[str]
    missing_keys: list[str]


def build_task_environment(session: Session, box: SecretBox, task: Task) -> TaskEnvironment:
    """Decrypted variables to inject in the task process (used by the engine)."""
    env: dict[str, str] = {}
    secrets: list[str] = []
    missing: list[str] = []
    for r in resolve(session, task):
        var = r.variable
        if var.value is None:
            missing.append(r.key)
            continue
        value = box.decrypt(var.value) if var.is_secret else var.value
        if var.is_secret:
            secrets.append(value)
        env[r.key] = value
    return TaskEnvironment(env=env, secret_values=secrets, missing_keys=missing)

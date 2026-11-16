from __future__ import annotations

from fastapi import APIRouter, status

from rts.api.deps import SecretBoxDep, SessionDep
from rts.models import VariableScope
from rts.schemas.common import ErrorOut
from rts.schemas.variables import VariableCreate, VariableOut, VariableUpdate
from rts.services import variables as svc
from rts.services.errors import InvalidInputError

router = APIRouter(prefix="/variables", tags=["Variáveis"], responses={404: {"model": ErrorOut}})


@router.get(
    "",
    response_model=list[VariableOut],
    summary="Listar variáveis (filtrar por escopo e dono)",
    description="Valores de variáveis secretas nunca são retornados.",
)
def list_variables(
    session: SessionDep, scope: VariableScope | None = None, owner_id: int | None = None
):
    if scope is None and owner_id is not None:
        raise InvalidInputError("Informe 'scope' junto com 'owner_id'.")
    return [svc.to_out(v) for v in svc.list_variables(session, scope, owner_id)]


@router.post(
    "",
    response_model=VariableOut,
    status_code=status.HTTP_201_CREATED,
    summary="Criar variável",
    responses={409: {"model": ErrorOut}},
)
def create_variable(data: VariableCreate, session: SessionDep, box: SecretBoxDep):
    var = svc.create_variable(session, box, data)
    session.commit()
    return svc.to_out(var)


@router.get("/{variable_id}", response_model=VariableOut, summary="Obter variável")
def get_variable(variable_id: int, session: SessionDep):
    return svc.to_out(svc.get_variable(session, variable_id))


@router.patch(
    "/{variable_id}",
    response_model=VariableOut,
    summary="Atualizar variável",
    description=(
        "Para segredos, omita `value` para manter o valor atual ou envie um novo para substituí-lo."
    ),
    responses={409: {"model": ErrorOut}},
)
def update_variable(variable_id: int, data: VariableUpdate, session: SessionDep, box: SecretBoxDep):
    var = svc.update_variable(session, box, variable_id, data)
    session.commit()
    return svc.to_out(var)


@router.delete("/{variable_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir variável")
def delete_variable(variable_id: int, session: SessionDep):
    svc.delete_variable(session, variable_id)
    session.commit()

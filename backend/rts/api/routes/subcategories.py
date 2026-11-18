from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from rts.api.deps import SessionDep, SettingsDep
from rts.schemas.common import ErrorOut
from rts.schemas.hierarchy import SubcategoryCreate, SubcategoryOut, SubcategoryUpdate
from rts.schemas.variables import EffectiveVariableOut
from rts.services import hierarchy as svc
from rts.services.variables import inherited_variables
from rts.services.workspaces import remove_workspaces, task_ids_under

router = APIRouter(
    prefix="/subcategories", tags=["Subcategorias"], responses={404: {"model": ErrorOut}}
)


@router.get("", response_model=list[SubcategoryOut], summary="Listar subcategorias")
def list_subcategories(session: SessionDep, group_id: int | None = None):
    return [svc.subcategory_to_out(s) for s in svc.list_subcategories(session, group_id)]


@router.post(
    "",
    response_model=SubcategoryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Criar subcategoria",
    responses={409: {"model": ErrorOut}},
)
def create_subcategory(data: SubcategoryCreate, session: SessionDep):
    sub = svc.create_subcategory(session, data)
    session.commit()
    return svc.subcategory_to_out(sub)


@router.get("/{subcategory_id}", response_model=SubcategoryOut, summary="Obter subcategoria")
def get_subcategory(subcategory_id: int, session: SessionDep):
    return svc.subcategory_to_out(svc.get_subcategory(session, subcategory_id))


@router.get(
    "/{subcategory_id}/effective-variables",
    response_model=list[EffectiveVariableOut],
    summary="Variáveis herdadas por tarefas desta subcategoria (Global → Grupo → Subcategoria)",
)
def get_inherited_variables(subcategory_id: int, session: SessionDep):
    return inherited_variables(session, svc.get_subcategory(session, subcategory_id))


class SequenceOrderIn(BaseModel):
    task_ids: list[int] = Field(description="Tarefas na ordem desejada (1ª, 2ª, ...).")


class SequenceOrderOut(BaseModel):
    task_ids: list[int] = Field(description="Ordem resultante da sequência (tarefas que herdam).")


@router.put(
    "/{subcategory_id}/sequence-order",
    response_model=SequenceOrderOut,
    summary="Definir a ordem das tarefas (modo sequencial)",
)
def set_sequence_order(subcategory_id: int, data: SequenceOrderIn, session: SessionDep):
    order = svc.set_sequence_order(session, subcategory_id, data.task_ids)
    session.commit()
    return SequenceOrderOut(task_ids=order)


@router.patch(
    "/{subcategory_id}",
    response_model=SubcategoryOut,
    summary="Atualizar subcategoria (inclui pausar/ativar e mover de grupo)",
    responses={409: {"model": ErrorOut}},
)
def update_subcategory(subcategory_id: int, data: SubcategoryUpdate, session: SessionDep):
    sub = svc.update_subcategory(session, subcategory_id, data)
    session.commit()
    return svc.subcategory_to_out(sub)


@router.delete(
    "/{subcategory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Excluir subcategoria (e suas tarefas)",
)
def delete_subcategory(subcategory_id: int, session: SessionDep, settings: SettingsDep):
    task_ids = task_ids_under(session, subcategory_id=subcategory_id)
    svc.delete_subcategory(session, subcategory_id)
    session.commit()
    remove_workspaces(settings, task_ids)

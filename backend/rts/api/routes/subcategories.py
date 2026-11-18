from __future__ import annotations

from fastapi import APIRouter, status

from rts.api.deps import SessionDep
from rts.schemas.common import ErrorOut
from rts.schemas.hierarchy import SubcategoryCreate, SubcategoryOut, SubcategoryUpdate
from rts.schemas.variables import EffectiveVariableOut
from rts.services import hierarchy as svc
from rts.services.variables import inherited_variables

router = APIRouter(
    prefix="/subcategories", tags=["Subcategorias"], responses={404: {"model": ErrorOut}}
)


@router.get("", response_model=list[SubcategoryOut], summary="Listar subcategorias")
def list_subcategories(session: SessionDep, group_id: int | None = None):
    return svc.list_subcategories(session, group_id)


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
    return sub


@router.get("/{subcategory_id}", response_model=SubcategoryOut, summary="Obter subcategoria")
def get_subcategory(subcategory_id: int, session: SessionDep):
    return svc.get_subcategory(session, subcategory_id)


@router.get(
    "/{subcategory_id}/effective-variables",
    response_model=list[EffectiveVariableOut],
    summary="Variáveis herdadas por tarefas desta subcategoria (Global → Grupo → Subcategoria)",
)
def get_inherited_variables(subcategory_id: int, session: SessionDep):
    return inherited_variables(session, svc.get_subcategory(session, subcategory_id))


@router.patch(
    "/{subcategory_id}",
    response_model=SubcategoryOut,
    summary="Atualizar subcategoria (inclui pausar/ativar e mover de grupo)",
    responses={409: {"model": ErrorOut}},
)
def update_subcategory(subcategory_id: int, data: SubcategoryUpdate, session: SessionDep):
    sub = svc.update_subcategory(session, subcategory_id, data)
    session.commit()
    return sub


@router.delete(
    "/{subcategory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Excluir subcategoria (e suas tarefas)",
)
def delete_subcategory(subcategory_id: int, session: SessionDep):
    svc.delete_subcategory(session, subcategory_id)
    session.commit()

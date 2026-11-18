from __future__ import annotations

from fastapi import APIRouter, status

from rts.api.deps import SessionDep, SettingsDep
from rts.schemas.common import ErrorOut
from rts.schemas.hierarchy import GroupCreate, GroupOut, GroupUpdate
from rts.services import hierarchy as svc
from rts.services.workspaces import remove_workspaces, task_ids_under

router = APIRouter(prefix="/groups", tags=["Grupos"], responses={404: {"model": ErrorOut}})


@router.get("", response_model=list[GroupOut], summary="Listar grupos")
def list_groups(session: SessionDep):
    return svc.list_groups(session)


@router.post(
    "",
    response_model=GroupOut,
    status_code=status.HTTP_201_CREATED,
    summary="Criar grupo",
    responses={409: {"model": ErrorOut}},
)
def create_group(data: GroupCreate, session: SessionDep):
    group = svc.create_group(session, data)
    session.commit()
    return group


@router.get("/{group_id}", response_model=GroupOut, summary="Obter grupo")
def get_group(group_id: int, session: SessionDep):
    return svc.get_group(session, group_id)


@router.patch(
    "/{group_id}",
    response_model=GroupOut,
    summary="Atualizar grupo (inclui pausar/ativar via is_active)",
    responses={409: {"model": ErrorOut}},
)
def update_group(group_id: int, data: GroupUpdate, session: SessionDep):
    group = svc.update_group(session, group_id, data)
    session.commit()
    return group


@router.delete(
    "/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Excluir grupo (e tudo abaixo dele)",
)
def delete_group(group_id: int, session: SessionDep, settings: SettingsDep):
    task_ids = task_ids_under(session, group_id=group_id)
    svc.delete_group(session, group_id)
    session.commit()
    remove_workspaces(settings, task_ids)

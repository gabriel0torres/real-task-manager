from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from rts.api.deps import SessionDep, SettingsDep
from rts.schemas.common import ErrorOut
from rts.schemas.hierarchy import GroupCreate, GroupOut, GroupUpdate
from rts.services import hierarchy as svc
from rts.services.durations import group_execution_times
from rts.services.workspaces import remove_workspaces, task_ids_under

router = APIRouter(prefix="/groups", tags=["Grupos"], responses={404: {"model": ErrorOut}})


@router.get("", response_model=list[GroupOut], summary="Listar grupos")
def list_groups(session: SessionDep):
    return [svc.group_to_out(g) for g in svc.list_groups(session)]


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
    return svc.group_to_out(group)


@router.get("/{group_id}", response_model=GroupOut, summary="Obter grupo")
def get_group(group_id: int, session: SessionDep):
    return svc.group_to_out(svc.get_group(session, group_id))


class ExecutionEntry(BaseModel):
    kind: str = Field(description="sequence (subcategoria sequencial) ou round (rodada paralela)")
    sequence_id: int | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    status: str = Field(description="success, failed, cancelled ou running")
    succeeded: int
    total: int


class SubcategoryExecutionTime(BaseModel):
    subcategory_id: int
    name: str
    execution_mode: str
    running: ExecutionEntry | None
    last: ExecutionEntry | None = Field(description="Última execução concluída.")
    average_ms: int | None = Field(description="Média das últimas execuções (sem as canceladas).")
    average_of: int


class GroupActivity(BaseModel):
    running_sequences: int
    running_runs: int
    waiting_runs: int


class GroupExecutionTimes(BaseModel):
    group_id: int
    subcategories: list[SubcategoryExecutionTime]
    total_last_ms: int = Field(description="Soma das durações das últimas execuções.")
    activity: GroupActivity = Field(description="O que está rodando ou na fila agora.")


@router.get(
    "/{group_id}/execution-times",
    response_model=GroupExecutionTimes,
    summary="Quanto tempo as automações do grupo levam, por subcategoria",
)
def execution_times(group_id: int, session: SessionDep):
    return group_execution_times(session, group_id)


@router.patch(
    "/{group_id}",
    response_model=GroupOut,
    summary="Atualizar grupo (inclui pausar/ativar via is_active)",
    responses={409: {"model": ErrorOut}},
)
def update_group(group_id: int, data: GroupUpdate, session: SessionDep):
    group = svc.update_group(session, group_id, data)
    session.commit()
    return svc.group_to_out(group)


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

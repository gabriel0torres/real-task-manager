from __future__ import annotations

from fastapi import APIRouter, status

from rts.api.deps import SessionDep, SettingsDep
from rts.schemas.common import ErrorOut
from rts.schemas.hierarchy import TaskCreate, TaskOut, TaskUpdate
from rts.schemas.variables import EffectiveVariableOut
from rts.services import hierarchy as svc
from rts.services.settings import get_default_timezone
from rts.services.variables import effective_variables
from rts.services.workspaces import remove_workspaces

router = APIRouter(prefix="/tasks", tags=["Tarefas"], responses={404: {"model": ErrorOut}})


@router.get("", response_model=list[TaskOut], summary="Listar tarefas")
def list_tasks(
    session: SessionDep,
    settings: SettingsDep,
    subcategory_id: int | None = None,
    group_id: int | None = None,
):
    tz = get_default_timezone(session, settings.default_timezone)
    return [svc.task_to_out(t, tz) for t in svc.list_tasks(session, subcategory_id, group_id)]


@router.post(
    "",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    summary="Criar tarefa",
    responses={409: {"model": ErrorOut}},
)
def create_task(data: TaskCreate, session: SessionDep, settings: SettingsDep):
    task = svc.create_task(session, data)
    session.commit()
    return svc.task_to_out(task, get_default_timezone(session, settings.default_timezone))


@router.get("/{task_id}", response_model=TaskOut, summary="Obter tarefa")
def get_task(task_id: int, session: SessionDep, settings: SettingsDep):
    task = svc.get_task(session, task_id)
    return svc.task_to_out(task, get_default_timezone(session, settings.default_timezone))


@router.patch(
    "/{task_id}",
    response_model=TaskOut,
    summary="Atualizar tarefa (inclui pausar/ativar e mover de subcategoria)",
    responses={409: {"model": ErrorOut}},
)
def update_task(task_id: int, data: TaskUpdate, session: SessionDep, settings: SettingsDep):
    task = svc.update_task(session, task_id, data)
    session.commit()
    return svc.task_to_out(task, get_default_timezone(session, settings.default_timezone))


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Excluir tarefa (e seu histórico)",
)
def delete_task(task_id: int, session: SessionDep, settings: SettingsDep):
    svc.delete_task(session, task_id)
    session.commit()
    remove_workspaces(settings, [task_id])


@router.get(
    "/{task_id}/effective-variables",
    response_model=list[EffectiveVariableOut],
    summary="Variáveis efetivas da tarefa (após herança) e sua origem",
)
def get_effective_variables(task_id: int, session: SessionDep):
    return effective_variables(session, svc.get_task(session, task_id))

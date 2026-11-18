"""Trigger tasks from scripts/CI with an API token."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import func, select

from rts.api.deps import SessionDep
from rts.api.routes.runs import run_to_out
from rts.models import Group, RunTrigger, Subcategory, Task
from rts.schemas.common import ErrorOut
from rts.schemas.runs import RunOut
from rts.services.auth import resolve_api_token
from rts.services.runs import request_manual_run

router = APIRouter(prefix="/trigger", tags=["Disparo via token"])

DESCRIPTION = (
    "Autentique com `Authorization: Bearer <token>` (crie o token em Configurações). "
    "Cria uma execução com gatilho `api`, respeitando a política de sobreposição. "
    'Exemplo: `curl -X POST -H "Authorization: Bearer rts_..." '
    "http://servidor:8000/api/v1/trigger/tasks/5`"
)


def _token_from(authorization: str | None, x_rts_token: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return x_rts_token


def _trigger(session, request: Request, task: Task, raw_token: str | None):
    token = resolve_api_token(session, raw_token)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de API inválido ou revogado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token.task_id is not None and token.task_id != task.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este token não pode disparar esta tarefa.",
        )
    run = request_manual_run(session, task.id, RunTrigger.API, by=f"token:{token.name}")
    session.commit()
    engine = getattr(request.app.state, "scheduler_engine", None)
    if engine is not None:
        engine.wake()
    return run_to_out(run)


responses = {401: {"model": ErrorOut}, 403: {"model": ErrorOut}, 404: {"model": ErrorOut}}


@router.post(
    "/tasks/{task_id}",
    response_model=RunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Disparar tarefa pelo ID",
    description=DESCRIPTION,
    responses=responses,
)
def trigger_by_id(
    task_id: int,
    request: Request,
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
    x_rts_token: Annotated[str | None, Header()] = None,
):
    raw = _token_from(authorization, x_rts_token)
    task = session.get(Task, task_id)
    if task is None:
        # Same answer as a bad token when the caller isn't authenticated.
        if resolve_api_token(session, raw) is None:
            raise HTTPException(status_code=401, detail="Token de API inválido ou revogado.")
        raise HTTPException(status_code=404, detail=f"Tarefa {task_id} não encontrada.")
    return _trigger(session, request, task, raw)


@router.post(
    "/{group}/{subcategory}/{task}",
    response_model=RunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Disparar tarefa pelo caminho grupo/subcategoria/tarefa",
    description=DESCRIPTION,
    responses=responses,
)
def trigger_by_path(
    group: str,
    subcategory: str,
    task: str,
    request: Request,
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
    x_rts_token: Annotated[str | None, Header()] = None,
):
    raw = _token_from(authorization, x_rts_token)
    found = session.scalars(
        select(Task)
        .join(Task.subcategory)
        .join(Subcategory.group)
        .where(
            func.lower(Group.name) == group.lower(),
            func.lower(Subcategory.name) == subcategory.lower(),
            func.lower(Task.name) == task.lower(),
        )
    ).first()
    if found is None:
        if resolve_api_token(session, raw) is None:
            raise HTTPException(status_code=401, detail="Token de API inválido ou revogado.")
        raise HTTPException(
            status_code=404, detail=f"Tarefa '{group}/{subcategory}/{task}' não encontrada."
        )
    return _trigger(session, request, found, raw)

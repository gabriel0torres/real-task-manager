"""Sequential subcategories: run the sequence now, follow it, cancel it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field

from rts.api.deps import CurrentUser, SessionDep
from rts.schemas.common import ErrorOut
from rts.schemas.runs import SequenceRunOut
from rts.services import sequences as svc
from rts.services.hierarchy import get_subcategory

router = APIRouter(tags=["Sequências"], responses={404: {"model": ErrorOut}})


def _wake_embedded_engine(request: Request) -> None:
    engine = getattr(request.app.state, "scheduler_engine", None)
    if engine is not None:
        engine.wake()


@router.get(
    "/subcategories/{subcategory_id}/sequences",
    response_model=list[SequenceRunOut],
    summary="Últimas execuções da sequência de uma subcategoria",
)
def list_sequences(
    subcategory_id: int,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    get_subcategory(session, subcategory_id)
    return [
        svc.sequence_to_out(session, s) for s in svc.list_sequences(session, subcategory_id, limit)
    ]


@router.post(
    "/subcategories/{subcategory_id}/sequences",
    response_model=SequenceRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Executar a sequência agora",
    description=(
        "Roda, uma depois da outra, as tarefas ativas da subcategoria que herdam o agendamento. "
        "Funciona mesmo com a subcategoria pausada."
    ),
    responses={409: {"model": ErrorOut}, 422: {"model": ErrorOut}},
)
def run_sequence(subcategory_id: int, session: SessionDep, request: Request, user: CurrentUser):
    seq = svc.request_sequence(session, get_subcategory(session, subcategory_id), by=user.username)
    session.commit()
    _wake_embedded_engine(request)
    return svc.sequence_to_out(session, seq)


class RunAllOut(BaseModel):
    mode: str = Field(description="parallel (todas ao mesmo tempo) ou sequential (uma por vez)")
    sequence_id: int | None
    run_ids: list[int] = Field(description="Execuções criadas (no modo sequencial, só a 1ª etapa).")
    task_count: int
    paused: list[str] = Field(description="Tarefas pausadas, que ficaram de fora.")


@router.post(
    "/subcategories/{subcategory_id}/run-all",
    response_model=RunAllOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Executar agora todas as tarefas ativas da subcategoria",
    description=(
        "Subcategoria paralela: todas ao mesmo tempo. Sequencial: uma depois da outra, na ordem "
        "da sequência (as de fora da sequência no fim). Tarefas pausadas ficam de fora."
    ),
    responses={409: {"model": ErrorOut}, 422: {"model": ErrorOut}},
)
def run_all(subcategory_id: int, session: SessionDep, request: Request, user: CurrentUser):
    sub = get_subcategory(session, subcategory_id)
    result = svc.run_all_tasks(session, sub, by=user.username)
    session.commit()
    _wake_embedded_engine(request)
    return result


class GroupInterruptOut(BaseModel):
    sequences_cancelled: int
    runs_cancelled: int = Field(
        description="Execuções interrompidas (rodando) ou canceladas (na fila)."
    )


@router.post(
    "/groups/{group_id}/interrupt",
    response_model=GroupInterruptOut,
    summary="Interromper tudo o que está rodando ou na fila no grupo",
    description=(
        "Cancela as sequências em andamento das subcategorias do grupo e interrompe as execuções "
        "em andamento ou na fila das suas tarefas. Os agendamentos continuam valendo."
    ),
)
def interrupt_group(group_id: int, session: SessionDep, request: Request):
    result = svc.interrupt_group(session, group_id)
    session.commit()
    _wake_embedded_engine(request)
    return result


@router.get("/sequences/{sequence_id}", response_model=SequenceRunOut, summary="Obter sequência")
def get_sequence(sequence_id: int, session: SessionDep):
    return svc.sequence_to_out(session, svc.get_sequence(session, sequence_id))


@router.post(
    "/sequences/{sequence_id}/cancel",
    response_model=SequenceRunOut,
    summary="Cancelar sequência",
    description="Cancela a etapa em andamento e não inicia as próximas.",
    responses={409: {"model": ErrorOut}},
)
def cancel_sequence(sequence_id: int, session: SessionDep, request: Request):
    seq = svc.cancel_sequence(session, sequence_id)
    session.commit()
    _wake_embedded_engine(request)
    return svc.sequence_to_out(session, seq)

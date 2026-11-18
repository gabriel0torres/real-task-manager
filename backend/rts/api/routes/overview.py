from __future__ import annotations

from fastapi import APIRouter

from rts.api.deps import SessionDep, SettingsDep
from rts.api.routes.runs import run_to_out, worker_status
from rts.schemas.overview import DashboardOut, TreeGroup
from rts.services.overview import build_tree, dashboard_data
from rts.services.settings import get_default_timezone

router = APIRouter(tags=["Visão geral"])


@router.get(
    "/tree",
    response_model=list[TreeGroup],
    summary="Árvore Grupos > Subcategorias > Tarefas com indicadores de status",
)
def tree(session: SessionDep):
    return build_tree(session)


@router.get("/dashboard", response_model=DashboardOut, summary="Dados do painel inicial")
def dashboard(session: SessionDep, settings: SettingsDep):
    data = dashboard_data(session, get_default_timezone(session, settings.default_timezone))
    data["running"] = [run_to_out(r) for r in data["running"]]
    data["recent_failures"] = [run_to_out(r) for r in data["recent_failures"]]
    data["worker"] = worker_status(session)
    return data

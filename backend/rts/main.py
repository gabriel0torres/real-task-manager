"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from rts import __version__
from rts.api.deps import require, require_by_method
from rts.api.routes import (
    auth,
    groups,
    notifications,
    overview,
    runs,
    subcategories,
    system,
    tasks,
    transfer,
    trigger,
    variables,
)
from rts.config import Settings, get_settings
from rts.db import make_engine, make_session_factory
from rts.security.crypto import SecretBox, load_secret_key
from rts.security.permissions import Permission
from rts.services.auth import LoginThrottle, ensure_admin
from rts.services.errors import ServiceError

log = logging.getLogger("rts")

API_PREFIX = "/api/v1"

DESCRIPTION = """
API do **Real Task Scheduler (RTS)**: agendador de tarefas self-hosted.

Hierarquia: **Global → Grupo → Subcategoria → Tarefa**. Variáveis são herdadas nessa
ordem e o nível mais específico sobrescreve o mais geral.

**Autenticação**: faça `POST /api/v1/auth/login`; a sessão fica num cookie httpOnly.
Para disparar tarefas a partir de scripts, crie um token de API em Configurações e use
`POST /api/v1/trigger/tasks/{id}` com `Authorization: Bearer <token>`.
"""


def _routers():
    """(router, guard) pairs. Reads need "view"; writes need the area's permission."""
    view = Depends(require(Permission.VIEW))
    config = Depends(require_by_method(Permission.MANAGE_CONFIG))
    settings = Depends(require_by_method(Permission.MANAGE_SETTINGS))
    return [
        (system.public_router, []),
        (auth.router, []),  # login is public; the other routes check the user themselves
        (trigger.router, []),  # API token
        (overview.router, [view]),
        (system.router, [view]),
        (groups.router, [config]),
        (subcategories.router, [config]),
        (tasks.router, [config]),
        (variables.router, [config]),
        (transfer.router, [config]),
        (runs.router, [Depends(require_by_method(Permission.RUN_TASKS))]),
        (system.settings_router, [settings]),
        (notifications.router, [settings]),
    ]


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA: static assets plus index.html for client-side routes."""
    index = dist / "index.html"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Não encontrado."})
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(levelname)s %(name)s: %(message)s"
    )
    settings.ensure_dirs()

    engine = make_engine(settings.effective_database_url)
    secret_box = SecretBox(load_secret_key(settings))
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_migrate:
            from rts.migrations.runner import upgrade_to_head

            upgrade_to_head(engine)
        with session_factory() as session:
            ensure_admin(session, settings)
        log.info("RTS %s iniciado (banco: %s)", __version__, engine.url.render_as_string())
        scheduler_engine = notifier = None
        if settings.embedded_worker:
            from rts.engine.context import EngineContext
            from rts.engine.scheduler import SchedulerEngine
            from rts.notifications.service import Notifier

            notifier = Notifier(session_factory, secret_box, settings)
            scheduler_engine = SchedulerEngine(
                EngineContext(settings, session_factory, secret_box, notifier=notifier)
            )
            scheduler_engine.start()
            app.state.scheduler_engine = scheduler_engine
            log.info("Motor de agendamento embutido na API (RTS_EMBEDDED_WORKER=true).")
        try:
            yield
        finally:
            if scheduler_engine is not None:
                scheduler_engine.stop()
            if notifier is not None:
                notifier.shutdown()
            engine.dispose()

    app = FastAPI(
        title="Real Task Scheduler",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.secret_box = secret_box
    app.state.login_throttle = LoginThrottle()

    @app.exception_handler(ServiceError)
    async def _service_error(_request: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(IntegrityError)
    async def _integrity_error(_request: Request, exc: IntegrityError):
        log.warning("Integrity error: %s", exc.orig)
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Operação viola uma restrição de integridade (registro duplicado?)."
            },
        )

    for router, guards in _routers():
        app.include_router(router, prefix=API_PREFIX, dependencies=guards)

    dist = settings.effective_frontend_dir
    if dist is not None:
        _mount_frontend(app, dist)
        log.info("Interface servida a partir de %s", dist)

    return app


def run() -> None:  # pragma: no cover - CLI entrypoint
    import uvicorn

    uvicorn.run("rts.main:create_app", factory=True, host="0.0.0.0", port=8000)

"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from rts import __version__
from rts.api.routes import (
    groups,
    overview,
    runs,
    subcategories,
    system,
    tasks,
    transfer,
    variables,
)
from rts.config import Settings, get_settings
from rts.db import make_engine, make_session_factory
from rts.security.crypto import SecretBox, load_secret_key
from rts.services.errors import ServiceError

log = logging.getLogger("rts")

API_PREFIX = "/api/v1"

DESCRIPTION = """
API do **Real Task Scheduler (RTS)**: agendador de tarefas self-hosted.

Hierarquia: **Global → Grupo → Subcategoria → Tarefa**. Variáveis são herdadas nessa
ordem e o nível mais específico sobrescreve o mais geral.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(levelname)s %(name)s: %(message)s"
    )
    settings.ensure_dirs()

    engine = make_engine(settings.effective_database_url)
    secret_box = SecretBox(load_secret_key(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_migrate:
            from rts.migrations.runner import upgrade_to_head

            upgrade_to_head(engine)
        log.info("RTS %s iniciado (banco: %s)", __version__, engine.url.render_as_string())
        scheduler_engine = None
        if settings.embedded_worker:
            from rts.engine.context import EngineContext
            from rts.engine.scheduler import SchedulerEngine

            scheduler_engine = SchedulerEngine(
                EngineContext(settings, app.state.session_factory, secret_box)
            )
            scheduler_engine.start()
            app.state.scheduler_engine = scheduler_engine
            log.info("Motor de agendamento embutido na API (RTS_EMBEDDED_WORKER=true).")
        try:
            yield
        finally:
            if scheduler_engine is not None:
                scheduler_engine.stop()
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
    app.state.session_factory = make_session_factory(engine)
    app.state.secret_box = secret_box

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

    for module in (overview, groups, subcategories, tasks, variables, runs, transfer, system):
        app.include_router(module.router, prefix=API_PREFIX)

    return app


def run() -> None:  # pragma: no cover - CLI entrypoint
    import uvicorn

    uvicorn.run("rts.main:create_app", factory=True, host="0.0.0.0", port=8000)

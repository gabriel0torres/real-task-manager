"""Export / import endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, model_validator

from rts.api.deps import SecretBoxDep, SessionDep, SettingsDep
from rts.schemas.common import ErrorOut
from rts.services.errors import InvalidInputError
from rts.services.settings import get_default_timezone
from rts.transfer.crypto import MIN_PASSWORD_LENGTH
from rts.transfer.exporter import export_config
from rts.transfer.format import Scope, SecretsMode
from rts.transfer.importer import ImportOptions, ImportReport, run_import

router = APIRouter(prefix="/transfer", tags=["Exportação e importação"])


class ExportRequest(BaseModel):
    scope: Scope
    id: int | None = Field(default=None, description="ID do grupo ou subcategoria (se aplicável).")
    secrets_mode: SecretsMode = Field(
        default="omit",
        description="`omit`: segredos sem valor (a preencher). `encrypted`: cifrados com senha.",
    )
    password: str | None = Field(default=None, description="Obrigatória para `encrypted`.")

    @model_validator(mode="after")
    def _check(self):
        if self.scope != "system" and self.id is None:
            raise ValueError("Informe 'id' para exportar um grupo ou subcategoria.")
        if self.secrets_mode == "encrypted" and len(self.password or "") < MIN_PASSWORD_LENGTH:
            raise ValueError(f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
        return self


@router.post(
    "/export",
    summary="Exportar configuração (YAML)",
    response_class=Response,
    responses={200: {"content": {"application/x-yaml": {}}}, 404: {"model": ErrorOut}},
)
def export(data: ExportRequest, session: SessionDep, box: SecretBoxDep, settings: SettingsDep):
    try:
        result = export_config(
            session,
            box,
            scope=data.scope,
            target_id=data.id,
            secrets_mode=data.secrets_mode,
            password=data.password,
            fallback_timezone=settings.default_timezone,
        )
    except ValueError as exc:
        raise InvalidInputError(str(exc)) from exc
    return Response(
        content=result.content.encode("utf-8"),
        media_type="application/x-yaml; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "X-RTS-Secrets": str(result.secrets_total),
            "Access-Control-Expose-Headers": "Content-Disposition, X-RTS-Secrets",
        },
    )


def _import(opts: ImportOptions, session, box, settings, dry_run: bool) -> ImportReport:
    return run_import(
        session,
        box,
        opts,
        dry_run=dry_run,
        fallback_timezone=get_default_timezone(session, settings.default_timezone),
    )


@router.post(
    "/import/preview",
    response_model=ImportReport,
    summary="Pré-visualizar importação (dry-run)",
    description=(
        "Valida o arquivo e o `schema_version` e simula a importação sem alterar nada. "
        "Mostra o que será criado, alterado, excluído ou pulado, os conflitos de nome "
        "(com as resoluções possíveis) e os segredos que ficarão sem valor."
    ),
)
def import_preview(
    opts: ImportOptions, session: SessionDep, box: SecretBoxDep, settings: SettingsDep
):
    return _import(opts, session, box, settings, dry_run=True)


@router.post(
    "/import/apply",
    response_model=ImportReport,
    summary="Aplicar importação (atômica)",
    description="Tudo ou nada: qualquer erro desfaz a importação inteira.",
    responses={422: {"model": ImportReport}},
)
def import_apply(
    opts: ImportOptions,
    session: SessionDep,
    box: SecretBoxDep,
    settings: SettingsDep,
    request: Request,
):
    report = _import(opts, session, box, settings, dry_run=False)
    if not report.valid:
        return JSONResponse(status_code=422, content=report.model_dump(mode="json"))
    engine = getattr(request.app.state, "scheduler_engine", None)
    if engine is not None:
        engine.wake()
    return report

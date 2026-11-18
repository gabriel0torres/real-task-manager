"""Notification channels, rules (global + per group) and test sends."""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, field_validator

from rts.api.deps import SecretBoxDep, SessionDep
from rts.models import NotificationRule
from rts.notifications import channels
from rts.notifications import service as svc
from rts.schemas.common import ErrorOut
from rts.services.hierarchy import get_group

router = APIRouter(
    prefix="/notifications", tags=["Notificações"], responses={404: {"model": ErrorOut}}
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------- channels
class SmtpIn(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    security: Literal["starttls", "ssl", "none"] | None = None
    username: str | None = Field(default=None, max_length=255)
    sender: str | None = Field(default=None, max_length=255)
    password: str | None = Field(
        default=None, description="Omitir mantém a senha atual; string vazia remove."
    )


class TelegramIn(BaseModel):
    bot_token: str | None = Field(
        default=None, description="Omitir mantém o token atual; string vazia remove."
    )


class ChannelsIn(BaseModel):
    smtp: SmtpIn | None = None
    telegram: TelegramIn | None = None


class SmtpOut(BaseModel):
    host: str
    port: int
    security: str
    username: str
    sender: str
    has_password: bool


class ChannelsOut(BaseModel):
    smtp: SmtpOut
    telegram: dict[str, bool]


@router.get("/channels", response_model=ChannelsOut, summary="Canais (SMTP, Telegram)")
def get_channels(session: SessionDep):
    return svc.channels_public(session)


@router.put(
    "/channels",
    response_model=ChannelsOut,
    summary="Configurar canais",
    description="Senha do SMTP e token do bot são cifrados e nunca retornados.",
)
def put_channels(data: ChannelsIn, session: SessionDep, box: SecretBoxDep):
    result = svc.update_channels(session, box, data.model_dump(exclude_unset=True))
    session.commit()
    return result


# --------------------------------------------------------------------------- rules
class RuleIn(BaseModel):
    enabled: bool = True
    on_failure: bool = True
    on_timeout: bool = True
    on_success: bool = False
    on_recovery: bool = False
    email_to: list[str] = Field(default_factory=list, max_length=50)
    telegram_chat_ids: list[str] = Field(default_factory=list, max_length=50)
    webhook_urls: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("email_to")
    @classmethod
    def _emails(cls, v: list[str]) -> list[str]:
        out = [e.strip() for e in v if e.strip()]
        for e in out:
            if not EMAIL_RE.match(e):
                raise ValueError(f"E-mail inválido: {e}")
        return out

    @field_validator("telegram_chat_ids")
    @classmethod
    def _chats(cls, v: list[str]) -> list[str]:
        out = [c.strip() for c in v if c.strip()]
        for c in out:
            if not re.fullmatch(r"-?\d+|@[A-Za-z0-9_]{4,}", c):
                raise ValueError(f"Chat do Telegram inválido: {c} (use o ID numérico ou @canal)")
        return out

    @field_validator("webhook_urls")
    @classmethod
    def _urls(cls, v: list[str]) -> list[str]:
        out = [u.strip() for u in v if u.strip()]
        for u in out:
            if not u.lower().startswith(("http://", "https://")):
                raise ValueError(f"URL de webhook inválida: {u}")
        return out


class RuleOut(RuleIn):
    exists: bool = Field(description="Falso quando ainda não foi configurada (valores padrão).")


def rule_out(rule: NotificationRule | None) -> RuleOut:
    if rule is None:
        return RuleOut(exists=False)
    return RuleOut(exists=True, **{f: getattr(rule, f) for f in svc.RULE_FIELDS})


class GroupRuleOut(BaseModel):
    group_id: int
    uses_own_rule: bool
    rule: RuleOut = Field(description="Regra própria do grupo, ou a global que ele herda.")


@router.get("/rules/global", response_model=RuleOut, summary="Regra global")
def get_global_rule(session: SessionDep):
    return rule_out(svc.get_rule(session, None))


@router.put("/rules/global", response_model=RuleOut, summary="Salvar regra global")
def put_global_rule(data: RuleIn, session: SessionDep):
    rule = svc.save_rule(session, None, data.model_dump())
    session.commit()
    return rule_out(rule)


@router.get(
    "/rules/groups/{group_id}", response_model=GroupRuleOut, summary="Regra efetiva do grupo"
)
def get_group_rule(group_id: int, session: SessionDep):
    get_group(session, group_id)
    own = svc.get_rule(session, group_id)
    return GroupRuleOut(
        group_id=group_id,
        uses_own_rule=own is not None,
        rule=rule_out(own or svc.get_rule(session, None)),
    )


@router.put(
    "/rules/groups/{group_id}",
    response_model=GroupRuleOut,
    summary="Sobrescrever a regra para o grupo",
)
def put_group_rule(group_id: int, data: RuleIn, session: SessionDep):
    get_group(session, group_id)
    rule = svc.save_rule(session, group_id, data.model_dump())
    session.commit()
    return GroupRuleOut(group_id=group_id, uses_own_rule=True, rule=rule_out(rule))


@router.delete(
    "/rules/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Voltar a usar a regra global",
)
def delete_group_rule(group_id: int, session: SessionDep):
    get_group(session, group_id)
    svc.delete_group_rule(session, group_id)
    session.commit()


# --------------------------------------------------------------------------- test
class TestIn(BaseModel):
    channel: Literal["email", "telegram", "webhook"]
    target: str = Field(min_length=1, max_length=500, description="E-mail, chat ID ou URL.")


class TestOut(BaseModel):
    ok: bool
    error: str | None = None


@router.post("/test", response_model=TestOut, summary="Enviar mensagem de teste")
def send_test(data: TestIn, session: SessionDep, box: SecretBoxDep):
    text = "Mensagem de teste do Real Task Scheduler: as notificações estão funcionando."
    try:
        if data.channel == "email":
            channels.send_email(
                svc.load_smtp(session, box), [data.target], "[RTS] Teste de notificação", text
            )
        elif data.channel == "telegram":
            channels.send_telegram(svc.load_telegram_token(session, box) or "", data.target, text)
        else:
            channels.send_webhook(data.target, {"event": "test", "message": text})
    except channels.ChannelError as exc:
        return TestOut(ok=False, error=str(exc))
    return TestOut(ok=True)

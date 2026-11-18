"""Login/logout, current user, password change and API tokens."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from rts.api.deps import SESSION_COOKIE, CurrentUser, SessionDep, SettingsDep, require
from rts.models import ApiToken, User
from rts.schemas.common import ErrorOut
from rts.security.permissions import ROLE_PERMISSIONS, Permission
from rts.services import auth as svc

router = APIRouter(prefix="/auth", tags=["Autenticação"])


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    must_change_password: bool
    permissions: list[str]
    last_login_at: datetime | None


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        role=user.role,
        must_change_password=user.must_change_password,
        permissions=sorted(p.value for p in ROLE_PERMISSIONS.get(user.role, ())),
        last_login_at=user.last_login_at,
    )


def _client_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "?"
    return f"{host}|{username.strip().lower()}"


@router.post(
    "/login",
    response_model=UserOut,
    summary="Entrar (cria a sessão no cookie)",
    responses={401: {"model": ErrorOut}, 429: {"model": ErrorOut}},
)
def login(
    data: LoginIn, request: Request, response: Response, session: SessionDep, settings: SettingsDep
):
    throttle: svc.LoginThrottle = request.app.state.login_throttle
    key = _client_key(request, data.username)
    wait = throttle.blocked_for(key)
    if wait > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Muitas tentativas. Tente novamente em {int(wait // 60) + 1} minuto(s).",
        )
    user = svc.authenticate(session, data.username, data.password)
    if user is None:
        throttle.fail(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário ou senha inválidos."
        )
    throttle.reset(key)
    token = svc.create_session(session, user, settings.session_ttl_hours)
    session.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return user_out(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sair")
def logout(request: Request, response: Response, session: SessionDep):
    svc.end_session(session, request.cookies.get(SESSION_COOKIE))
    session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get(
    "/me", response_model=UserOut, summary="Usuário atual", responses={401: {"model": ErrorOut}}
)
def me(user: CurrentUser):
    return user_out(user)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


@router.post("/change-password", response_model=UserOut, summary="Trocar a própria senha")
def change_password(
    data: ChangePasswordIn, request: Request, user: CurrentUser, session: SessionDep
):
    db_user = session.get(User, user.id)
    svc.change_password(
        session,
        db_user,
        data.current_password,
        data.new_password,
        request.cookies.get(SESSION_COOKIE),
    )
    session.commit()
    return user_out(db_user)


# --------------------------------------------------------------------------- API tokens
class TokenIn(BaseModel):
    name: str = Field(max_length=100)
    task_id: int | None = Field(default=None, description="Restringe o token a uma tarefa.")


class TokenOut(BaseModel):
    id: int
    name: str
    prefix: str
    task_id: int | None
    task_name: str | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class TokenCreatedOut(TokenOut):
    token: str = Field(description="Exibido somente agora; guarde-o em local seguro.")


def token_out(token: ApiToken, session) -> dict:
    from rts.models import Task

    task = session.get(Task, token.task_id) if token.task_id else None
    return {
        "id": token.id,
        "name": token.name,
        "prefix": token.prefix,
        "task_id": token.task_id,
        "task_name": task.name if task else None,
        "created_at": token.created_at,
        "last_used_at": token.last_used_at,
        "revoked_at": token.revoked_at,
    }


manage = [Depends(require(Permission.MANAGE_SETTINGS))]


@router.get(
    "/tokens", response_model=list[TokenOut], summary="Listar tokens de API", dependencies=manage
)
def list_tokens(session: SessionDep):
    return [token_out(t, session) for t in svc.list_api_tokens(session)]


@router.post(
    "/tokens",
    response_model=TokenCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Criar token de API (para disparar tarefas)",
    dependencies=manage,
)
def create_token(data: TokenIn, user: CurrentUser, session: SessionDep):
    db_user = session.get(User, user.id)
    token, raw = svc.create_api_token(session, db_user, data.name, data.task_id)
    session.commit()
    return {**token_out(token, session), "token": raw}


@router.delete(
    "/tokens/{token_id}",
    response_model=TokenOut,
    summary="Revogar token de API",
    dependencies=manage,
)
def revoke_token(token_id: int, session: SessionDep):
    token = svc.revoke_api_token(session, token_id)
    session.commit()
    return token_out(token, session)

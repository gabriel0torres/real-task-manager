"""FastAPI dependencies: database session, secrets, settings, authentication."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from rts.config import Settings
from rts.models import User
from rts.security.crypto import SecretBox
from rts.security.permissions import Permission, role_has
from rts.services.auth import resolve_session

SESSION_COOKIE = "rts_session"


def get_session(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_secret_box(request: Request) -> SecretBox:
    return request.app.state.secret_box


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


SessionDep = Annotated[Session, Depends(get_session)]
SecretBoxDep = Annotated[SecretBox, Depends(get_secret_box)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def current_user(request: Request, session: SessionDep) -> User:
    user = resolve_session(session, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Faça login para continuar."
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def _check(user: User, permission: Permission) -> User:
    if not role_has(user.role, permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão.")
    return user


def require(permission: Permission) -> Callable[[User], User]:
    def checker(user: CurrentUser) -> User:
        return _check(user, permission)

    return checker


def require_by_method(write: Permission, read: Permission = Permission.VIEW):
    """Router-level guard: GET/HEAD need ``read``, anything else needs ``write``."""

    def checker(request: Request, user: CurrentUser) -> User:
        return _check(user, read if request.method in ("GET", "HEAD") else write)

    return checker

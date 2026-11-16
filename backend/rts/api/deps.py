"""FastAPI dependencies.

Authentication is added in phase 5; routes already go through these
dependencies so a ``current_user`` / permission check can be plugged in here.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from rts.config import Settings
from rts.security.crypto import SecretBox


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

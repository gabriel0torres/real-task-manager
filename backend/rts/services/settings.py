"""Persistent key/value settings stored in the ``settings`` table."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from rts.models import Setting

DEFAULT_TIMEZONE = "default_timezone"
CONFIG_REVISION = "config_revision"


def get_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Setting, key)
    return default if row is None or row.value is None else row.value


def set_setting(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


def get_default_timezone(session: Session, fallback: str) -> str:
    return get_setting(session, DEFAULT_TIMEZONE, fallback)


def bump_config_revision(session: Session) -> int:
    """Signal the scheduling engine that schedules must be reloaded."""
    revision = int(get_setting(session, CONFIG_REVISION, 0)) + 1
    set_setting(session, CONFIG_REVISION, revision)
    return revision

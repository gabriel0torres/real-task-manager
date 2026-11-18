"""Authentication: bootstrap admin, login sessions, API tokens."""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from rts.config import Settings
from rts.models import ApiToken, User, UserSession
from rts.models.base import utcnow
from rts.security.passwords import (
    burn_time,
    generate_password,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)
from rts.services.errors import InvalidInputError, NotFoundError
from rts.services.hierarchy import get_task

log = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8
API_TOKEN_PREFIX = "rts_"


# --------------------------------------------------------------------------- bootstrap
def ensure_admin(session: Session, settings: Settings) -> str | None:
    """Create the admin user on first start. Returns a generated password, if any."""
    if session.scalar(select(func.count(User.id))):
        return None
    generated = None
    password = settings.admin_password
    if not password:
        password = generated = generate_password()
    elif len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"RTS_ADMIN_PASSWORD deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres."
        )
    session.add(
        User(
            username=settings.admin_username,
            password_hash=hash_password(password),
            role="admin",
            must_change_password=generated is not None,
        )
    )
    session.commit()
    if generated:
        log.warning(
            "Usuário administrador criado: '%s' com senha gerada: %s  "
            "(troque-a no primeiro acesso ou defina RTS_ADMIN_PASSWORD)",
            settings.admin_username,
            generated,
        )
    else:
        log.info("Usuário administrador '%s' criado.", settings.admin_username)
    return generated


# --------------------------------------------------------------------------- brute force
class LoginThrottle:
    """At most ``limit`` failed logins per key in ``window`` seconds."""

    def __init__(self, limit: int = 5, window: float = 300.0) -> None:
        self.limit = limit
        self.window = window
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked_for(self, key: str) -> float:
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            return self.window - (now - q[0]) if len(q) >= self.limit else 0.0

    def fail(self, key: str) -> None:
        with self._lock:
            self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


# --------------------------------------------------------------------------- login/sessions
def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.scalars(
        select(User).where(func.lower(User.username) == username.strip().lower())
    ).first()
    if user is None or not user.is_active:
        burn_time(password)
        return None
    return user if verify_password(password, user.password_hash) else None


def create_session(session: Session, user: User, ttl_hours: int) -> str:
    token = generate_token()
    now = utcnow()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=ttl_hours),
        )
    )
    user.last_login_at = now
    # Housekeeping: drop expired sessions.
    session.execute(delete(UserSession).where(UserSession.expires_at < now))
    session.flush()
    return token


def resolve_session(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = session.scalars(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    ).first()
    now = utcnow()
    if row is None or row.expires_at < now or not row.user.is_active:
        return None
    if (now - row.last_seen_at).total_seconds() > 300:
        row.last_seen_at = now
        session.commit()
    return row.user


def end_session(session: Session, token: str | None) -> None:
    if token:
        session.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
        session.flush()


def change_password(
    session: Session, user: User, current: str, new: str, keep_token: str | None
) -> None:
    if not verify_password(current, user.password_hash):
        raise InvalidInputError("Senha atual incorreta.")
    if len(new) < MIN_PASSWORD_LENGTH:
        raise InvalidInputError(
            f"A nova senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres."
        )
    if new == current:
        raise InvalidInputError("A nova senha deve ser diferente da atual.")
    user.password_hash = hash_password(new)
    user.must_change_password = False
    # Sign out every other browser.
    stmt = delete(UserSession).where(UserSession.user_id == user.id)
    if keep_token:
        stmt = stmt.where(UserSession.token_hash != hash_token(keep_token))
    session.execute(stmt)
    session.flush()


# --------------------------------------------------------------------------- API tokens
def create_api_token(
    session: Session, user: User, name: str, task_id: int | None
) -> tuple[ApiToken, str]:
    name = name.strip()
    if not name:
        raise InvalidInputError("Dê um nome ao token.")
    if task_id is not None:
        get_task(session, task_id)
    raw = generate_token(API_TOKEN_PREFIX)
    token = ApiToken(
        name=name,
        token_hash=hash_token(raw),
        prefix=raw[: len(API_TOKEN_PREFIX) + 6],
        user_id=user.id,
        task_id=task_id,
    )
    session.add(token)
    session.flush()
    return token, raw


def list_api_tokens(session: Session) -> list[ApiToken]:
    return list(session.scalars(select(ApiToken).order_by(ApiToken.id.desc())))


def revoke_api_token(session: Session, token_id: int) -> ApiToken:
    token = session.get(ApiToken, token_id)
    if token is None:
        raise NotFoundError(f"Token {token_id} não encontrado.")
    if token.revoked_at is None:
        token.revoked_at = utcnow()
    session.flush()
    return token


def resolve_api_token(session: Session, raw: str | None) -> ApiToken | None:
    if not raw:
        return None
    token = session.scalars(select(ApiToken).where(ApiToken.token_hash == hash_token(raw))).first()
    if token is None or token.revoked_at is not None:
        return None
    user = session.get(User, token.user_id)
    if user is None or not user.is_active:
        return None
    token.last_used_at = utcnow()
    return token

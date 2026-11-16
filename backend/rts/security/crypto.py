"""Symmetric encryption of secret variables (Fernet)."""

from __future__ import annotations

import contextlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

from rts.config import Settings

log = logging.getLogger(__name__)

GENERATE_HINT = (
    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


class SecretKeyError(RuntimeError):
    pass


class SecretDecryptError(RuntimeError):
    pass


class SecretBox:
    def __init__(self, key: bytes | str) -> None:
        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise SecretKeyError(
                f"Chave secreta inválida: deve ser uma chave Fernet (base64, 32 bytes). "
                f"Gere uma com: {GENERATE_HINT}"
            ) from exc

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise SecretDecryptError(
                "Não foi possível decifrar um segredo: a RTS_SECRET_KEY mudou?"
            ) from exc


def load_secret_key(settings: Settings) -> bytes:
    """Return the Fernet key from env, the key file, or generate and persist a new one."""
    if settings.secret_key:
        key = settings.secret_key.strip().encode("ascii")
        SecretBox(key)  # validate early
        return key

    key_file = settings.secret_key_file
    if key_file.exists():
        key = key_file.read_bytes().strip()
        SecretBox(key)
        return key

    key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    with contextlib.suppress(OSError):  # best effort (e.g. Windows)
        os.chmod(key_file, 0o600)
    log.warning(
        "RTS_SECRET_KEY não definida: uma nova chave foi gerada em %s. "
        "Faça backup deste arquivo - sem ele, as variáveis secretas não podem ser recuperadas.",
        key_file,
    )
    return key

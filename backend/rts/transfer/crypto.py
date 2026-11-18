"""Password-based encryption of secrets inside export files.

Key = PBKDF2-HMAC-SHA256(password, random salt, N iterations) -> Fernet. The
``check`` token (a known plaintext encrypted with the key) lets the importer
tell a wrong password apart from a corrupted value.
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ALGORITHM = "fernet-pbkdf2-sha256"
DEFAULT_ITERATIONS = 480_000
MIN_PASSWORD_LENGTH = 8
_CHECK_PLAINTEXT = b"rts-export-password-check"


class WrongPasswordError(ValueError):
    pass


def _derive(password: str, salt: bytes, iterations: int) -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8"))))


class ExportCipher:
    def __init__(self, fernet: Fernet, salt: bytes, iterations: int) -> None:
        self._fernet = fernet
        self.salt = salt
        self.iterations = iterations

    @classmethod
    def create(cls, password: str, iterations: int | None = None) -> ExportCipher:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
        iterations = iterations or DEFAULT_ITERATIONS
        salt = os.urandom(16)
        return cls(_derive(password, salt, iterations), salt, iterations)

    @classmethod
    def open(cls, password: str, salt_b64: str, iterations: int, check: str) -> ExportCipher:
        salt = base64.b64decode(salt_b64)
        cipher = cls(_derive(password, salt, iterations), salt, iterations)
        try:
            if cipher._fernet.decrypt(check.encode("ascii")) != _CHECK_PLAINTEXT:
                raise WrongPasswordError("Senha incorreta.")
        except (InvalidToken, ValueError) as exc:
            raise WrongPasswordError("Senha incorreta.") from exc
        return cipher

    def header(self) -> dict:
        return {
            "algorithm": ALGORITHM,
            "iterations": self.iterations,
            "salt": base64.b64encode(self.salt).decode("ascii"),
            "check": self._fernet.encrypt(_CHECK_PLAINTEXT).decode("ascii"),
        }

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Valor cifrado corrompido no arquivo.") from exc

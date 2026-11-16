"""Masking of secret values in log output."""

from __future__ import annotations

import re
from collections.abc import Iterable

MASK = "****"


class SecretMasker:
    """Replaces every occurrence of any secret value with ``****``.

    Longer secrets are matched first so a secret that contains another one is
    fully masked.
    """

    def __init__(self, secrets: Iterable[str | None]) -> None:
        values = sorted({s for s in secrets if s}, key=len, reverse=True)
        self._pattern = re.compile("|".join(re.escape(v) for v in values)) if values else None

    def __bool__(self) -> bool:
        return self._pattern is not None

    def mask(self, text: str) -> str:
        if self._pattern is None or not text:
            return text
        return self._pattern.sub(MASK, text)


def mask_secrets(text: str, secrets: Iterable[str | None]) -> str:
    return SecretMasker(secrets).mask(text)

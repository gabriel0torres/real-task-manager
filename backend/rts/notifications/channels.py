"""Delivery channels (stdlib only). Each function raises ``ChannelError`` on failure."""

from __future__ import annotations

import json
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Literal

TIMEOUT_SECONDS = 15
TELEGRAM_API = "https://api.telegram.org"
USER_AGENT = "RealTaskScheduler"


class ChannelError(RuntimeError):
    pass


@dataclass
class SmtpConfig:
    host: str
    port: int = 587
    security: Literal["starttls", "ssl", "none"] = "starttls"
    username: str | None = None
    password: str | None = None
    sender: str = ""


def send_email(cfg: SmtpConfig, to: list[str], subject: str, body: str) -> None:
    if not cfg.host or not cfg.sender:
        raise ChannelError("SMTP não configurado (servidor e remetente são obrigatórios).")
    msg = EmailMessage()
    msg["From"] = cfg.sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        if cfg.security == "ssl":
            client = smtplib.SMTP_SSL(
                cfg.host, cfg.port, timeout=TIMEOUT_SECONDS, context=ssl.create_default_context()
            )
        else:
            client = smtplib.SMTP(cfg.host, cfg.port, timeout=TIMEOUT_SECONDS)
        with client:
            if cfg.security == "starttls":
                client.starttls(context=ssl.create_default_context())
            if cfg.username:
                client.login(cfg.username, cfg.password or "")
            client.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise ChannelError(f"Falha no envio de e-mail: {exc}") from exc


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None) -> int:
    if not url.lower().startswith(("http://", "https://")):
        raise ChannelError("A URL deve começar com http:// ou https://")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.status
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode("utf-8", errors="replace")
        raise ChannelError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ChannelError(f"Falha de conexão: {getattr(exc, 'reason', exc)}") from exc


def send_telegram(bot_token: str, chat_id: str, text: str) -> None:
    if not bot_token:
        raise ChannelError("Token do bot do Telegram não configurado.")
    try:
        _post_json(
            f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
            {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
        )
    except ChannelError as exc:
        # Never leak the bot token (it is part of the URL) into logs.
        raise ChannelError(str(exc).replace(bot_token, "****")) from None


def send_webhook(url: str, payload: dict) -> None:
    _post_json(url, payload)

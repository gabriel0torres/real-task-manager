"""Command line: ``rts start | api | worker | admin reset-password | version``.

``rts start`` runs the API and the scheduling engine as two separate processes
(so the UI can crash or restart without interrupting executions) and restarts
either of them if it dies. Services (systemd / Windows) run ``rts api`` and
``rts worker`` directly instead.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import time

from rts import __version__

log = logging.getLogger("rts.cli")


def _self_command(*args: str) -> list[str]:
    """How to re-invoke this program (frozen executable or python -m rts)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "rts", *args]


def cmd_api(args: argparse.Namespace) -> int:
    import uvicorn

    from rts.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "rts.main:create_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=settings.log_level.lower(),
    )
    return 0


def cmd_worker(_args: argparse.Namespace) -> int:
    from rts.worker import main

    main()
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    """Supervise API + worker until Ctrl+C / SIGTERM."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    extra = []
    if args.host:
        extra += ["--host", args.host]
    if args.port:
        extra += ["--port", str(args.port)]
    specs = {"worker": _self_command("worker"), "api": _self_command("api", *extra)}
    procs: dict[str, subprocess.Popen] = {}
    stopping = False

    def spawn(name: str) -> None:
        procs[name] = subprocess.Popen(specs[name])
        log.info("Processo %s iniciado (pid %s).", name, procs[name].pid)

    def stop(*_a) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    # API first (it applies migrations and creates the admin user).
    spawn("api")
    time.sleep(3)
    spawn("worker")
    last_restart: dict[str, float] = {}
    while not stopping:
        time.sleep(1)
        for name, proc in list(procs.items()):
            if proc.poll() is not None and not stopping:
                wait = 1 if time.monotonic() - last_restart.get(name, 0) > 60 else 10
                log.warning(
                    "Processo %s terminou (código %s); reiniciando em %ss.",
                    name,
                    proc.returncode,
                    wait,
                )
                time.sleep(wait)
                last_restart[name] = time.monotonic()
                spawn(name)

    log.info("Encerrando...")
    for proc in procs.values():
        if proc.poll() is None:
            if os.name == "nt":
                proc.terminate()
            else:
                proc.send_signal(signal.SIGTERM)
    deadline = time.monotonic() + 30
    for proc in procs.values():
        try:
            proc.wait(max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    from sqlalchemy import func, select

    from rts.config import get_settings
    from rts.db import make_engine, make_session_factory
    from rts.migrations.runner import upgrade_to_head
    from rts.models import User, UserSession
    from rts.security.passwords import generate_password, hash_password

    settings = get_settings()
    settings.ensure_dirs()
    engine = make_engine(settings.effective_database_url)
    upgrade_to_head(engine)
    username = args.username or settings.admin_username
    password = args.password or generate_password()
    with make_session_factory(engine)() as session:
        user = session.scalars(
            select(User).where(func.lower(User.username) == username.lower())
        ).first()
        if user is None:
            user = User(username=username, role="admin", password_hash="")
            session.add(user)
        user.password_hash = hash_password(password)
        user.must_change_password = args.password is None
        user.is_active = True
        session.query(UserSession).filter(UserSession.user_id == user.id).delete()
        session.commit()
    print(f"Senha do usuário '{username}' redefinida: {password}")
    if args.password is None:
        print("Ela deverá ser trocada no próximo acesso.")
    return 0


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"Real Task Scheduler {__version__}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rts", description="Real Task Scheduler")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("start", "inicia a API e o motor de agendamento (Ctrl+C para parar)"),
        ("api", "inicia só a API e a interface web"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--host", help="endereço (padrão: RTS_HOST ou 0.0.0.0)")
        p.add_argument("--port", type=int, help="porta (padrão: RTS_PORT ou 8000)")
    sub.add_parser("worker", help="inicia só o motor de agendamento")
    sub.add_parser("version", help="mostra a versão")

    admin = sub.add_parser("admin", help="administração").add_subparsers(
        dest="admin_command", required=True
    )
    reset = admin.add_parser("reset-password", help="redefine a senha de um usuário administrador")
    reset.add_argument("--username", help="padrão: RTS_ADMIN_USERNAME")
    reset.add_argument("--password", help="nova senha (padrão: gera uma aleatória)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "start": cmd_start,
        "api": cmd_api,
        "worker": cmd_worker,
        "version": cmd_version,
    }
    if args.command == "admin":
        return cmd_reset_password(args)
    return handlers[args.command](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

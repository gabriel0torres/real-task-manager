"""Worker process entrypoint: ``rts-worker`` or ``python -m rts.worker``.

Runs the scheduling engine independently from the API, so the web interface can
go down without interrupting executions.
"""

from __future__ import annotations

import logging
import signal
import threading
import time

from rts.config import get_settings
from rts.db import make_engine, make_session_factory
from rts.engine.context import EngineContext
from rts.engine.scheduler import SchedulerEngine
from rts.migrations.runner import upgrade_to_head
from rts.security.crypto import SecretBox, load_secret_key

log = logging.getLogger("rts.worker")


def _migrate_with_retry(engine, attempts: int = 5, delay: float = 2.0) -> None:
    # The API may be migrating the same database at the same moment.
    for attempt in range(1, attempts + 1):
        try:
            upgrade_to_head(engine)
            return
        except Exception:
            if attempt == attempts:
                raise
            log.warning(
                "Migration falhou (tentativa %d/%d), tentando novamente...", attempt, attempts
            )
            time.sleep(delay)


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings.ensure_dirs()
    db_engine = make_engine(settings.effective_database_url)
    if settings.auto_migrate:
        _migrate_with_retry(db_engine)

    ctx = EngineContext(
        settings=settings,
        session_factory=make_session_factory(db_engine),
        secret_box=SecretBox(load_secret_key(settings)),
    )
    engine = SchedulerEngine(ctx)

    stop = threading.Event()

    def _handle_signal(signum, _frame):
        log.info("Sinal %s recebido, encerrando...", signum)
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    engine.start()
    try:
        while not stop.wait(1):
            pass
    finally:
        engine.stop()
        db_engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    main()

"""Alembic environment.

Uses the connection passed by ``rts.migrations.runner`` when called from the
application, otherwise builds an engine from the RTS settings (CLI usage).
"""

from __future__ import annotations

from alembic import context

import rts.models  # noqa: F401  (registers all tables)
from rts.db import Base, make_engine

config = context.config
target_metadata = Base.metadata


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )


def run_migrations_offline() -> None:
    from rts.config import get_settings

    context.configure(
        url=get_settings().effective_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    from rts.config import get_settings

    settings = get_settings()
    settings.ensure_dirs()
    engine = make_engine(settings.effective_database_url)
    with engine.connect() as conn:
        _configure(conn)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

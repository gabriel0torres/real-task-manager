"""inherited schedules: group/subcategory schedules and task schedule mode

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODE = sa.Enum(
    "own",
    "inherit",
    "manual",
    name="task_schedule_mode",
    native_enum=False,
    create_constraint=False,  # added explicitly below (not possible on SQLite)
    length=20,
)


def upgrade() -> None:
    # Plain ADD COLUMN (no batch mode): rebuilding these SQLite tables would drop their
    # expression-based unique indexes, which SQLAlchemy cannot reflect.
    for table in ("groups", "subcategories"):
        op.add_column(
            table,
            sa.Column(
                "cron_expressions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
            ),
        )
        op.add_column(table, sa.Column("timezone", sa.String(length=64), nullable=True))

    op.add_column("tasks", sa.Column("schedule_mode", _MODE, nullable=False, server_default="own"))
    if op.get_bind().dialect.name != "sqlite":
        # SQLite can't add a constraint to an existing table; the ORM validates the value.
        op.create_check_constraint(
            "task_schedule_mode", "tasks", "schedule_mode IN ('own', 'inherit', 'manual')"
        )

    # Until now an empty schedule meant "manual only"; keep that meaning explicit.
    # Done in Python because JSON columns can't be compared portably in SQL.
    tasks = sa.table(
        "tasks",
        sa.column("id", sa.Integer()),
        sa.column("cron_expressions", sa.JSON()),
        sa.column("schedule_mode", sa.String()),
    )
    conn = op.get_bind()
    manual = [
        row.id
        for row in conn.execute(sa.select(tasks.c.id, tasks.c.cron_expressions))
        if not row.cron_expressions
    ]
    if manual:
        conn.execute(tasks.update().where(tasks.c.id.in_(manual)).values(schedule_mode="manual"))


def downgrade() -> None:
    op.drop_column("tasks", "schedule_mode")
    for table in ("groups", "subcategories"):
        op.drop_column(table, "timezone")
        op.drop_column(table, "cron_expressions")

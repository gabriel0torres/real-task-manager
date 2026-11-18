"""sequential subcategories: execution mode, task order and sequence runs

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str, constraint: bool = True) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=constraint, length=20)


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"

    op.create_table(
        "sequence_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subcategory_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _enum("sequence_status", "running", "success", "failed", "cancelled", "skipped"),
            nullable=False,
        ),
        sa.Column(
            "trigger",
            _enum("sequence_trigger", "scheduled", "manual", "retry", "api"),
            nullable=False,
        ),
        sa.Column("triggered_by", sa.String(length=128), nullable=True),
        sa.Column("task_ids", sa.JSON(), nullable=False),
        sa.Column("current_index", sa.Integer(), nullable=False),
        sa.Column("stop_on_failure", sa.Boolean(), nullable=False),
        _ts("scheduled_for", nullable=True),
        _ts("created_at"),
        _ts("finished_at", nullable=True),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["subcategory_id"],
            ["subcategories.id"],
            name=op.f("fk_sequence_runs_subcategory_id_subcategories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sequence_runs")),
    )
    op.create_index("ix_sequence_runs_subcategory_id", "sequence_runs", ["subcategory_id"])

    # Plain ADD COLUMN on subcategories/tasks: rebuilding those SQLite tables would drop
    # their expression-based unique indexes (see 0003).
    op.add_column(
        "subcategories",
        sa.Column(
            "execution_mode",
            _enum("subcategory_execution_mode", "parallel", "sequential", constraint=False),
            nullable=False,
            server_default="parallel",
        ),
    )
    op.add_column(
        "subcategories",
        sa.Column("stop_on_failure", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("subcategories", _ts("last_sequence_fire_at", nullable=True))
    op.add_column("tasks", sa.Column("sequence_position", sa.Integer(), nullable=True))
    if not sqlite:
        op.create_check_constraint(
            "subcategory_execution_mode",
            "subcategories",
            "execution_mode IN ('parallel', 'sequential')",
        )

    # runs has only plain indexes, so batch mode (needed for the foreign key on SQLite)
    # rebuilds it safely.
    # resolve_fks=False: don't reflect the referenced tables (tasks has an expression index).
    with op.batch_alter_table("runs", reflect_kwargs={"resolve_fks": False}) as batch:
        batch.add_column(sa.Column("sequence_run_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("sequence_index", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_runs_sequence_run_id_sequence_runs"),
            "sequence_runs",
            ["sequence_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_runs_sequence_run_id", ["sequence_run_id"])


def downgrade() -> None:
    with op.batch_alter_table("runs", reflect_kwargs={"resolve_fks": False}) as batch:
        batch.drop_index("ix_runs_sequence_run_id")
        batch.drop_constraint(op.f("fk_runs_sequence_run_id_sequence_runs"), type_="foreignkey")
        batch.drop_column("sequence_index")
        batch.drop_column("sequence_run_id")
    op.drop_column("tasks", "sequence_position")
    op.drop_column("subcategories", "last_sequence_fire_at")
    op.drop_column("subcategories", "stop_on_failure")
    op.drop_column("subcategories", "execution_mode")
    op.drop_index("ix_sequence_runs_subcategory_id", table_name="sequence_runs")
    op.drop_table("sequence_runs")

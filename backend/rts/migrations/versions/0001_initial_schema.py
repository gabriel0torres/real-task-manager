"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


def _partial(scope: str) -> dict:
    where = sa.text(f"scope = '{scope}'")
    return {"sqlite_where": where, "postgresql_where": where}


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
    )
    op.create_index("uq_groups_name_ci", "groups", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    )

    op.create_table(
        "worker_heartbeat",
        sa.Column("worker_id", sa.String(length=100), nullable=False),
        _ts("started_at"),
        _ts("last_seen"),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("worker_id", name=op.f("pk_worker_heartbeat")),
    )

    op.create_table(
        "subcategories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_subcategories_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subcategories")),
    )
    op.create_index("ix_subcategories_group_id", "subcategories", ["group_id"])
    op.create_index(
        "uq_subcategories_group_name_ci",
        "subcategories",
        ["group_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subcategory_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column(
            "shell",
            _enum("task_shell", "bash", "sh", "cmd", "powershell", "pwsh", "python"),
            nullable=True,
        ),
        sa.Column("working_dir", sa.String(length=1024), nullable=True),
        sa.Column("cron_expressions", sa.JSON(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("retry_interval_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "overlap_policy",
            _enum("task_overlap_policy", "skip", "queue", "parallel"),
            nullable=False,
        ),
        sa.Column(
            "misfire_policy", _enum("task_misfire_policy", "run_once", "ignore"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _ts("last_fire_at", nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["subcategory_id"],
            ["subcategories.id"],
            name=op.f("fk_tasks_subcategory_id_subcategories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index("ix_tasks_subcategory_id", "tasks", ["subcategory_id"])
    op.create_index(
        "uq_tasks_subcategory_name_ci",
        "tasks",
        ["subcategory_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _enum(
                "run_status",
                "pending",
                "running",
                "success",
                "failed",
                "timeout",
                "cancelled",
                "skipped",
            ),
            nullable=False,
        ),
        sa.Column(
            "trigger", _enum("run_trigger", "scheduled", "manual", "retry", "api"), nullable=False
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("root_run_id", sa.Integer(), nullable=True),
        _ts("scheduled_for", nullable=True),
        _ts("created_at"),
        _ts("started_at", nullable=True),
        _ts("finished_at", nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("triggered_by", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(
            ["root_run_id"],
            ["runs.id"],
            name=op.f("fk_runs_root_run_id_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_runs_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    op.create_index("ix_runs_root_run_id", "runs", ["root_run_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_task_created", "runs", ["task_id", "created_at"])

    op.create_table(
        "variables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "scope",
            _enum("variable_scope", "global", "group", "subcategory", "task"),
            nullable=False,
        ),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("subcategory_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("is_secret", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "(scope = 'global' AND group_id IS NULL AND subcategory_id IS NULL"
            " AND task_id IS NULL)"
            " OR (scope = 'group' AND group_id IS NOT NULL AND subcategory_id IS NULL"
            " AND task_id IS NULL)"
            " OR (scope = 'subcategory' AND group_id IS NULL AND subcategory_id IS NOT NULL"
            " AND task_id IS NULL)"
            " OR (scope = 'task' AND group_id IS NULL AND subcategory_id IS NULL"
            " AND task_id IS NOT NULL)",
            name=op.f("ck_variables_scope_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_variables_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subcategory_id"],
            ["subcategories.id"],
            name=op.f("fk_variables_subcategory_id_subcategories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_variables_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_variables")),
    )
    op.create_index("ix_variables_group_id", "variables", ["group_id"])
    op.create_index("ix_variables_subcategory_id", "variables", ["subcategory_id"])
    op.create_index("ix_variables_task_id", "variables", ["task_id"])
    op.create_index(
        "uq_variables_global_key", "variables", ["key"], unique=True, **_partial("global")
    )
    op.create_index(
        "uq_variables_group_key",
        "variables",
        ["group_id", "key"],
        unique=True,
        **_partial("group"),
    )
    op.create_index(
        "uq_variables_subcategory_key",
        "variables",
        ["subcategory_id", "key"],
        unique=True,
        **_partial("subcategory"),
    )
    op.create_index(
        "uq_variables_task_key",
        "variables",
        ["task_id", "key"],
        unique=True,
        **_partial("task"),
    )

    op.create_table(
        "run_log_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        _ts("ts"),
        sa.Column("stream", _enum("log_stream", "stdout", "stderr", "system"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_run_log_chunks_run_id_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_log_chunks")),
    )
    op.create_index("ix_run_log_chunks_run_seq", "run_log_chunks", ["run_id", "seq"], unique=True)


def downgrade() -> None:
    op.drop_table("run_log_chunks")
    op.drop_table("variables")
    op.drop_table("runs")
    op.drop_table("tasks")
    op.drop_table("subcategories")
    op.drop_table("worker_heartbeat")
    op.drop_table("settings")
    op.drop_table("groups")

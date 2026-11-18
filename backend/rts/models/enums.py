"""Domain enumerations (values are persisted, keep them stable)."""

from __future__ import annotations

from enum import StrEnum


class VariableScope(StrEnum):
    GLOBAL = "global"
    GROUP = "group"
    SUBCATEGORY = "subcategory"
    TASK = "task"


# Resolution order: later entries override earlier ones.
SCOPE_PRECEDENCE: tuple[VariableScope, ...] = (
    VariableScope.GLOBAL,
    VariableScope.GROUP,
    VariableScope.SUBCATEGORY,
    VariableScope.TASK,
)


class OverlapPolicy(StrEnum):
    SKIP = "skip"
    QUEUE = "queue"
    PARALLEL = "parallel"


class MisfirePolicy(StrEnum):
    RUN_ONCE = "run_once"
    IGNORE = "ignore"


class ScheduleMode(StrEnum):
    """Where a task's schedule comes from."""

    OWN = "own"  # the task's own cron expressions
    INHERIT = "inherit"  # its subcategory's schedule, else its group's
    MANUAL = "manual"  # never fires on a schedule


class ExecutionMode(StrEnum):
    """How the tasks of a subcategory that inherit its schedule run when it fires."""

    PARALLEL = "parallel"  # each one on its own, at the same time
    SEQUENTIAL = "sequential"  # one after the other, in the configured order


class SequenceStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"  # every step succeeded
    FAILED = "failed"  # stopped on a failure, or finished with failed steps
    CANCELLED = "cancelled"
    SKIPPED = "skipped"  # the previous sequence was still running (or nothing to run)


class Shell(StrEnum):
    BASH = "bash"
    SH = "sh"
    CMD = "cmd"
    POWERSHELL = "powershell"
    PWSH = "pwsh"
    PYTHON = "python"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


FINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.SUCCESS,
        RunStatus.FAILED,
        RunStatus.TIMEOUT,
        RunStatus.CANCELLED,
        RunStatus.SKIPPED,
    }
)


class RunTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    RETRY = "retry"
    API = "api"


class LogStream(StrEnum):
    STDOUT = "stdout"
    STDERR = "stderr"
    SYSTEM = "system"

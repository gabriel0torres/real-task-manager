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

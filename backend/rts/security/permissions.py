"""Permissions per role.

Today there is a single ``admin`` role with every permission. Routes already
declare the permission they need, so adding roles (e.g. "operator" that can
run tasks but not edit them) only requires a new entry in ROLE_PERMISSIONS.
"""

from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    VIEW = "view"  # read configuration, runs and logs
    RUN_TASKS = "run_tasks"  # run now / cancel
    MANAGE_CONFIG = "manage_config"  # create/edit/delete groups, tasks, variables, import
    MANAGE_SETTINGS = "manage_settings"  # settings, notifications, retention, API tokens


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "admin": frozenset(Permission),
}


def role_has(role: str, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())

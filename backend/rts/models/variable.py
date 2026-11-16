"""Variables attached to any level of the hierarchy."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from rts.db import Base
from rts.models.base import TimestampMixin, str_enum
from rts.models.enums import VariableScope

_SCOPE_CHECK = (
    "(scope = 'global' AND group_id IS NULL AND subcategory_id IS NULL AND task_id IS NULL)"
    " OR (scope = 'group' AND group_id IS NOT NULL AND subcategory_id IS NULL"
    " AND task_id IS NULL)"
    " OR (scope = 'subcategory' AND group_id IS NULL AND subcategory_id IS NOT NULL"
    " AND task_id IS NULL)"
    " OR (scope = 'task' AND group_id IS NULL AND subcategory_id IS NULL"
    " AND task_id IS NOT NULL)"
)


def _partial_unique(name: str, scope: VariableScope, *cols: str) -> Index:
    where = text(f"scope = '{scope.value}'")
    return Index(name, *cols, unique=True, sqlite_where=where, postgresql_where=where)


class Variable(TimestampMixin, Base):
    __tablename__ = "variables"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[VariableScope] = mapped_column(
        str_enum(VariableScope, "variable_scope"), nullable=False
    )
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    subcategory_id: Mapped[int | None] = mapped_column(
        ForeignKey("subcategories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )

    key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Plain text, or a Fernet token when is_secret. NULL means "value pending"
    # (e.g. secrets imported without value).
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_secret: Mapped[bool] = mapped_column(default=False, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        CheckConstraint(_SCOPE_CHECK, name="scope_owner"),
        _partial_unique("uq_variables_global_key", VariableScope.GLOBAL, "key"),
        _partial_unique("uq_variables_group_key", VariableScope.GROUP, "group_id", "key"),
        _partial_unique(
            "uq_variables_subcategory_key", VariableScope.SUBCATEGORY, "subcategory_id", "key"
        ),
        _partial_unique("uq_variables_task_key", VariableScope.TASK, "task_id", "key"),
    )

    @property
    def owner_id(self) -> int | None:
        return {
            VariableScope.GLOBAL: None,
            VariableScope.GROUP: self.group_id,
            VariableScope.SUBCATEGORY: self.subcategory_id,
            VariableScope.TASK: self.task_id,
        }[self.scope]

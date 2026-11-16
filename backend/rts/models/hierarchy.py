"""Group -> Subcategory -> Task hierarchy."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rts.db import Base
from rts.models.base import TimestampMixin, UTCDateTime, str_enum
from rts.models.enums import MisfirePolicy, OverlapPolicy, Shell

if TYPE_CHECKING:
    from rts.models.run import Run
    from rts.models.variable import Variable


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    subcategories: Mapped[list[Subcategory]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Subcategory.name",
    )
    variables: Mapped[list[Variable]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="Variable.key"
    )

    __table_args__ = (Index("uq_groups_name_ci", func.lower(name), unique=True),)


class Subcategory(TimestampMixin, Base):
    __tablename__ = "subcategories"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    group: Mapped[Group] = relationship(back_populates="subcategories")
    tasks: Mapped[list[Task]] = relationship(
        back_populates="subcategory",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Task.name",
    )
    variables: Mapped[list[Variable]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="Variable.key"
    )

    __table_args__ = (
        Index("uq_subcategories_group_name_ci", group_id, func.lower(name), unique=True),
    )

    @property
    def is_effectively_active(self) -> bool:
        return bool(self.is_active and self.group.is_active)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    subcategory_id: Mapped[int] = mapped_column(
        ForeignKey("subcategories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    command: Mapped[str] = mapped_column(Text, nullable=False)
    shell: Mapped[Shell | None] = mapped_column(str_enum(Shell, "task_shell"), nullable=True)
    working_dir: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # One or more standard 5-field cron expressions (fires when any matches).
    cron_expressions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    overlap_policy: Mapped[OverlapPolicy] = mapped_column(
        str_enum(OverlapPolicy, "task_overlap_policy"), default=OverlapPolicy.SKIP, nullable=False
    )
    misfire_policy: Mapped[MisfirePolicy] = mapped_column(
        str_enum(MisfirePolicy, "task_misfire_policy"),
        default=MisfirePolicy.IGNORE,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    # Last scheduled fire time processed by the engine; base for missed-run detection.
    last_fire_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    subcategory: Mapped[Subcategory] = relationship(back_populates="tasks")
    variables: Mapped[list[Variable]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="Variable.key"
    )
    runs: Mapped[list[Run]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("uq_tasks_subcategory_name_ci", subcategory_id, func.lower(name), unique=True),
    )

    @property
    def is_effectively_active(self) -> bool:
        """A task only runs if it, its subcategory and its group are all active."""
        sub = self.subcategory
        return bool(self.is_active and sub.is_active and sub.group.is_active)

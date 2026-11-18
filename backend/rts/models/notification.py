"""Notification rules: one global rule (group_id NULL) plus optional per-group overrides."""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from rts.db import Base
from rts.models.base import TimestampMixin


class NotificationRule(TimestampMixin, Base):
    __tablename__ = "notification_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL = global rule. A group rule replaces the global one for that group.
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    on_failure: Mapped[bool] = mapped_column(default=True, nullable=False)
    on_timeout: Mapped[bool] = mapped_column(default=True, nullable=False)
    on_success: Mapped[bool] = mapped_column(default=False, nullable=False)
    on_recovery: Mapped[bool] = mapped_column(default=False, nullable=False)
    email_to: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    telegram_chat_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    webhook_urls: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

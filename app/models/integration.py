"""Connections to JIRA / Azure DevOps, their value mappings and a log of every sync run."""
import json
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project


class Integration(TimestampMixin, Base):
    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)  # "Payments JIRA"
    kind: Mapped[str] = mapped_column(String(20))  # "jira" or "ado"
    base_url: Mapped[str] = mapped_column(String(255))
    remote_project: Mapped[str | None] = mapped_column(String(100))  # JIRA key / ADO project
    username: Mapped[str | None] = mapped_column(String(255))
    # The API token / PAT, encrypted with Fernet (app/security.py). Never plain text.
    encrypted_token: Mapped[str | None] = mapped_column(Text)
    local_project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    # Extra settings as JSON text: JQL / WIQL filter, work item type, conflict policy...
    config_json: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=False)  # scheduled status sync
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sync_status: Mapped[str | None] = mapped_column(String(20))  # ok / error
    last_sync_message: Mapped[str | None] = mapped_column(Text)

    local_project: Mapped["Project | None"] = relationship()
    mappings: Mapped[list["IntegrationMapping"]] = relationship(
        back_populates="integration", cascade="all, delete-orphan"
    )
    sync_logs: Mapped[list["SyncLog"]] = relationship(
        back_populates="integration", cascade="all, delete-orphan", order_by="SyncLog.id.desc()"
    )

    @property
    def config(self) -> dict:
        try:
            return json.loads(self.config_json or "{}")
        except ValueError:
            return {}

    @config.setter
    def config(self, value: dict) -> None:
        self.config_json = json.dumps(value)


class IntegrationMapping(Base):
    """Translates one value, e.g. our status "In Review" <-> JIRA status "Code Review"."""

    __tablename__ = "integration_mappings"
    __table_args__ = (UniqueConstraint("integration_id", "field", "local_value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(30))  # "status", "priority", "task_type"
    local_value: Mapped[str] = mapped_column(String(50))
    remote_value: Mapped[str] = mapped_column(String(100))

    integration: Mapped[Integration] = relationship(back_populates="mappings")


class SyncLog(Base):
    """One row per import / push / status-sync run, including conflicts found."""

    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(30))  # import, sync, push, test
    status: Mapped[str] = mapped_column(String(20))  # ok, partial, error
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    conflicts: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)  # summary + conflict details
    triggered_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    integration: Mapped[Integration] = relationship(back_populates="sync_logs")

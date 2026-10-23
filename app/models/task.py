"""Tasks and the things hanging off a task: status history, comments, attachments."""
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import TaskPriority, TaskStatus, TaskType, enum_column
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.integration import Integration
    from app.models.project import Project
    from app.models.time_entry import TimeEntry
    from app.models.user import User


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        # Fast lookup of a task imported from JIRA / ADO
        Index("ix_tasks_external", "external_source", "external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(enum_column(TaskStatus), default=TaskStatus.TODO, index=True)
    priority: Mapped[TaskPriority] = mapped_column(enum_column(TaskPriority), default=TaskPriority.MEDIUM)
    task_type: Mapped[TaskType] = mapped_column(enum_column(TaskType), default=TaskType.OTHER)
    estimate_hours: Mapped[float | None] = mapped_column(Float)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    # Link to a JIRA issue / ADO work item. external_source is "jira" or "ado".
    external_source: Mapped[str | None] = mapped_column(String(20))
    external_id: Mapped[str | None] = mapped_column(String(50))  # e.g. "PAY-123"
    external_url: Mapped[str | None] = mapped_column(String(500))
    integration_id: Mapped[int | None] = mapped_column(
        ForeignKey("integrations.id", ondelete="SET NULL"), index=True
    )
    # Two-way sync bookkeeping: both sides' status at the last successful sync
    external_status: Mapped[str | None] = mapped_column(String(100))
    synced_status: Mapped[str | None] = mapped_column(String(20))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)

    project: Mapped["Project"] = relationship(back_populates="tasks")
    assignee: Mapped["User | None"] = relationship(
        back_populates="assigned_tasks", foreign_keys=[assignee_id]
    )
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_id])
    integration: Mapped["Integration | None"] = relationship()
    time_entries: Mapped[list["TimeEntry"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    status_history: Mapped[list["TaskStatusHistory"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskStatusHistory.id"
    )
    comments: Mapped[list["TaskComment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskComment.created_at"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )

    @property
    def total_hours(self) -> float:
        """All hours logged against this task."""
        return round(sum(entry.hours for entry in self.time_entries), 2)

    @property
    def is_overdue(self) -> bool:
        return self.due_date is not None and self.status != TaskStatus.DONE and self.due_date < date.today()

    @property
    def key(self) -> str:
        """Readable id such as "PAY-12"."""
        return f"{self.project.key}-{self.id}" if self.project else str(self.id)

    def __repr__(self) -> str:
        return f"<Task {self.id} {self.title!r} {self.status}>"


class TaskStatusHistory(Base):
    """One row each time a task changes status: who, when, from what, to what."""

    __tablename__ = "task_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[TaskStatus | None] = mapped_column(enum_column(TaskStatus))  # None = new task
    to_status: Mapped[TaskStatus] = mapped_column(enum_column(TaskStatus))
    changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped[Task] = relationship(back_populates="status_history")
    changed_by: Mapped["User | None"] = relationship()


class TaskComment(TimestampMixin, Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)

    task: Mapped[Task] = relationship(back_populates="comments")
    author: Mapped["User | None"] = relationship()


class Attachment(Base):
    """A file uploaded to a task. The file lives on disk; this row says where."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255))  # the name the user uploaded
    stored_path: Mapped[str] = mapped_column(String(500))  # where we saved it
    content_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped[Task] = relationship(back_populates="attachments")
    uploaded_by: Mapped["User | None"] = relationship()

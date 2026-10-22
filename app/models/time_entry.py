"""Hours a user logged on a task on a given day."""
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class TimeEntry(TimestampMixin, Base):
    __tablename__ = "time_entries"
    __table_args__ = (
        # The database itself refuses 0 or 30 hours
        CheckConstraint("hours > 0 AND hours <= 24", name="hours_range"),
        Index("ix_time_entries_user_date", "user_id", "work_date"),  # timesheet queries
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    work_date: Mapped[date] = mapped_column(Date)
    hours: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(500))

    user: Mapped["User"] = relationship(back_populates="time_entries")
    task: Mapped["Task"] = relationship(back_populates="time_entries")

    def __repr__(self) -> str:
        return f"<TimeEntry {self.work_date} {self.hours}h task={self.task_id}>"


class RunningTimer(Base):
    """A started-but-not-stopped timer. At most one per user; stopping it writes a TimeEntry."""

    __tablename__ = "running_timers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(String(500))

    user: Mapped["User"] = relationship()
    task: Mapped["Task"] = relationship()

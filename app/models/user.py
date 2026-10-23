"""Users, roles, and the user_roles link table (many-to-many)."""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:  # only for type hints; avoids circular imports at runtime
    from app.models.project import ProjectMember
    from app.models.task import Task
    from app.models.time_entry import TimeEntry

# Link table: one row per (user, role) pair.
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)  # Admin, PM, BA
    description: Mapped[str | None] = mapped_column(String(200))

    users: Mapped[list["User"]] = relationship(secondary=user_roles, back_populates="roles")

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    hashed_password: Mapped[str] = mapped_column(String(255))  # never the real password
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    job_title: Mapped[str | None] = mapped_column(String(100))
    weekly_capacity_hours: Mapped[float] = mapped_column(Float, default=40.0)  # for utilisation %
    # Locks the account for a while after too many wrong passwords
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, back_populates="users")
    memberships: Mapped[list["ProjectMember"]] = relationship(back_populates="user")
    assigned_tasks: Mapped[list["Task"]] = relationship(
        back_populates="assignee", foreign_keys="Task.assignee_id"
    )
    time_entries: Mapped[list["TimeEntry"]] = relationship(back_populates="user")

    @property
    def role_names(self) -> list[str]:
        return [role.name for role in self.roles]

    def has_role(self, *names: str) -> bool:
        """True if the user has at least one of the given roles."""
        return any(name in self.role_names for name in names)

    @property
    def is_admin(self) -> bool:
        return self.has_role("Admin")

    @property
    def is_manager(self) -> bool:
        """Admins and PMs see every project, dashboards and reports."""
        return self.has_role("Admin", "PM")

    @property
    def initials(self) -> str:
        parts = self.full_name.split()
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    def __repr__(self) -> str:
        return f"<User {self.email}>"

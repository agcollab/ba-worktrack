"""BA artefacts: requirements, their acceptance criteria (UAC) and test cases.

Filled by hand or by the AI Studio.
"""
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import TaskPriority, TestCaseStatus, enum_column
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.task import Task
    from app.models.user import User


class Requirement(TimestampMixin, Base):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="Functional")  # or "Non-functional"
    status: Mapped[str] = mapped_column(String(20), default="Draft")  # Draft, Approved
    source: Mapped[str] = mapped_column(String(20), default="Manual")  # Manual or AI
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    project: Mapped["Project"] = relationship(back_populates="requirements")
    task: Mapped["Task | None"] = relationship()
    created_by: Mapped["User | None"] = relationship()
    criteria: Mapped[list["AcceptanceCriterion"]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan", order_by="AcceptanceCriterion.position"
    )
    test_cases: Mapped[list["TestCase"]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan"
    )


class AcceptanceCriterion(TimestampMixin, Base):
    """One acceptance criterion, ideally in Given / When / Then form."""

    __tablename__ = "acceptance_criteria"

    id: Mapped[int] = mapped_column(primary_key=True)
    requirement_id: Mapped[int] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=1)  # display order
    given_text: Mapped[str | None] = mapped_column(Text)
    when_text: Mapped[str | None] = mapped_column(Text)
    then_text: Mapped[str] = mapped_column(Text)

    requirement: Mapped[Requirement] = relationship(back_populates="criteria")


class TestCase(TimestampMixin, Base):
    __tablename__ = "test_cases"
    __test__ = False  # tells pytest "this is not a test class" despite the name

    id: Mapped[int] = mapped_column(primary_key=True)
    requirement_id: Mapped[int] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    preconditions: Mapped[str | None] = mapped_column(Text)
    steps: Mapped[str] = mapped_column(Text)  # numbered steps, one per line
    expected_result: Mapped[str] = mapped_column(Text)
    priority: Mapped[TaskPriority] = mapped_column(enum_column(TaskPriority), default=TaskPriority.MEDIUM)
    status: Mapped[TestCaseStatus] = mapped_column(
        enum_column(TestCaseStatus), default=TestCaseStatus.NOT_RUN
    )

    requirement: Mapped[Requirement] = relationship(back_populates="test_cases")

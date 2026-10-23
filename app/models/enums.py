"""Fixed lists of allowed values (enums) shared by the models.

Each enum is a StrEnum, so TaskStatus.DONE == "Done" and it is stored in the
database as the readable text "Done", not as a number.
"""
from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class TaskStatus(StrEnum):
    TODO = "To Do"
    IN_PROGRESS = "In Progress"
    IN_REVIEW = "In Review"
    DONE = "Done"


class TaskType(StrEnum):
    REQUIREMENTS = "Requirements"
    UAC = "UAC"
    TESTING = "Testing"
    MEETING = "Meeting"
    ANALYSIS = "Analysis"
    OTHER = "Other"


class TaskPriority(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class TestCaseStatus(StrEnum):
    NOT_RUN = "Not Run"
    PASSED = "Passed"
    FAILED = "Failed"
    BLOCKED = "Blocked"


def enum_column(enum_class: type[StrEnum]) -> SAEnum:
    """A column type that stores the enum's text value ("In Progress").

    native_enum=False -> a plain VARCHAR in SQLite; SQLAlchemy still refuses
    values that are not in the enum before they reach the database.
    """
    return SAEnum(
        enum_class,
        values_callable=lambda members: [m.value for m in members],
        native_enum=False,
        length=20,
        validate_strings=True,
    )

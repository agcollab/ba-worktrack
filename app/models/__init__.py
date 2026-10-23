"""Import every model here.

Alembic and the tests look at Base.metadata to find tables. A model only
"registers" its table when its file is imported, so this file imports them all.
Elsewhere you can write:  from app.models import Task, User
"""
from app.models.ai_log import AIGenerationLog
from app.models.audit import AuditLog
from app.models.enums import TaskPriority, TaskStatus, TaskType, TestCaseStatus
from app.models.integration import Integration, IntegrationMapping, SyncLog
from app.models.item_type import ItemType
from app.models.project import Project, ProjectMember
from app.models.report import GeneratedReport
from app.models.requirement import AcceptanceCriterion, Requirement, TestCase
from app.models.task import Attachment, Task, TaskComment, TaskStatusHistory
from app.models.time_entry import RunningTimer, TimeEntry
from app.models.user import Role, User, user_roles

__all__ = [
    "AIGenerationLog",
    "AcceptanceCriterion",
    "Attachment",
    "AuditLog",
    "GeneratedReport",
    "Integration",
    "IntegrationMapping",
    "ItemType",
    "Project",
    "ProjectMember",
    "Requirement",
    "Role",
    "RunningTimer",
    "SyncLog",
    "Task",
    "TaskComment",
    "TaskPriority",
    "TaskStatus",
    "TaskStatusHistory",
    "TaskType",
    "TestCase",
    "TestCaseStatus",
    "TimeEntry",
    "User",
    "user_roles",
]

"""Pydantic shapes for the JSON API (/api/v1)."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import TaskPriority, TaskStatus, TaskType


class TokenRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    full_name: str
    role_names: list[str]
    weekly_capacity_hours: float


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    key: str
    name: str
    description: str | None
    is_active: bool


class TaskIn(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    task_type: TaskType = TaskType.OTHER
    assignee_id: int | None = None
    estimate_hours: float | None = Field(default=None, ge=0, le=1000)
    due_date: date | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    priority: TaskPriority | None = None
    task_type: TaskType | None = None
    assignee_id: int | None = None
    estimate_hours: float | None = Field(default=None, ge=0, le=1000)
    due_date: date | None = None


class StatusIn(BaseModel):
    status: TaskStatus


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    key: str
    project_id: int
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    task_type: TaskType
    type_label: str  # the JIRA / ADO item type when imported, else task_type
    is_read_only: bool
    assignee_id: int | None
    estimate_hours: float | None
    total_hours: float
    due_date: date | None
    is_overdue: bool
    external_source: str | None
    external_id: str | None
    external_url: str | None
    created_at: datetime
    updated_at: datetime


class TimeEntryIn(BaseModel):
    task_id: int
    work_date: date
    hours: float = Field(gt=0, le=24)
    note: str | None = Field(default=None, max_length=500)


class TimeEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    task_id: int
    work_date: date
    hours: float
    note: str | None

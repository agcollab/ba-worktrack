"""JSON API under /api/v1 for scripts and other tools. Authenticate with a Bearer token
from POST /api/v1/auth/token. Browser sessions (cookie) work too."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import csrf_protect, get_current_user
from app.models import TaskStatus, User
from app.reports.metrics import MetricFilters, Metrics, default_period
from app.routers.auth import rate_limited
from app.schemas import (
    ProjectOut,
    StatusIn,
    TaskIn,
    TaskOut,
    TaskPatch,
    TimeEntryIn,
    TimeEntryOut,
    Token,
    TokenRequest,
    UserOut,
)
from app.security import create_access_token
from app.services import audit, time_tracking, users
from app.services import projects as project_service
from app.services import tasks as task_service
from app.services.audit import client_ip
from app.services.errors import ServiceError
from app.services.tasks import TaskFilters

router = APIRouter(prefix="/api/v1", tags=["api"], dependencies=[Depends(csrf_protect)])


@router.post("/auth/token", response_model=Token)
def token(request: Request, body: TokenRequest, db: Session = Depends(get_db)):
    if rate_limited("api:" + (client_ip(request) or "unknown")):
        raise ServiceError("Too many attempts; wait a minute.")
    user = users.authenticate(db, body.email, body.password)
    audit.record(db, "auth.api_token", user=user, entity=user, request=request)
    db.commit()
    return Token(access_token=create_access_token(user.id), expires_in=settings.ACCESS_TOKEN_MINUTES * 60)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/projects", response_model=list[ProjectOut])
def projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return project_service.list_projects(db, user)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(q: str | None = None, project_id: int | None = None, status: list[TaskStatus] | None = Query(None),
               assignee_id: int | None = None, overdue: bool = False, limit: int = Query(100, le=1000),
               offset: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    filters = TaskFilters(q=q, project_id=project_id, status=[s.value for s in status or []],
                          assignee_id=assignee_id, overdue=overdue)
    return task_service.search_tasks(db, user, filters, limit=limit, offset=offset)


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.create_task(db, user, body.project_id, body.title, body.description, body.priority,
                                    body.task_type, body.assignee_id, body.estimate_hours, body.due_date)
    db.commit()
    return task_service.get_task(db, user, task.id)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return task_service.get_task(db, user, task_id)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def patch_task(task_id: int, body: TaskPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, task_id)
    data = body.model_dump(exclude_unset=True)
    task_service.update_task(
        db, user, task, data.get("title", task.title), data.get("description", task.description),
        data.get("priority") or task.priority, data.get("task_type") or task.task_type,
        data.get("assignee_id", task.assignee_id), data.get("estimate_hours", task.estimate_hours),
        data.get("due_date", task.due_date),
    )
    db.commit()
    return task_service.get_task(db, user, task_id)


@router.post("/tasks/{task_id}/status", response_model=TaskOut)
def set_status(task_id: int, body: StatusIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, task_id)
    task_service.change_status(db, user, task, body.status)
    db.commit()
    return task_service.get_task(db, user, task_id)


@router.get("/time-entries", response_model=list[TimeEntryOut])
def list_time(start: date | None = None, end: date | None = None, user_id: int | None = None,
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    end = end or date.today()
    start = start or end - timedelta(days=6)
    return time_tracking.entries_between(db, user, start, end, user_id)


@router.post("/time-entries", response_model=TimeEntryOut, status_code=201)
def create_time(body: TimeEntryIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, body.task_id)
    entry = time_tracking.log_time(db, user, task, body.work_date, body.hours, body.note)
    db.commit()
    return entry


@router.get("/metrics/summary")
def metrics_summary(start: date | None = None, end: date | None = None, project_id: int | None = None,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    default_start, default_end = default_period()
    filters = MetricFilters(start=start or default_start, end=end or default_end, project_id=project_id,
                            user_id=None if user.is_manager else user.id)
    summary = Metrics(db, user, filters).summary()
    summary["estimate_vs_actual"].pop("tasks", None)
    return {"start": filters.start, "end": filters.end, **summary}

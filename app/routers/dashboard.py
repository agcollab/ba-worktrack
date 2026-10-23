"""The home page: "My work" for everyone, plus team KPIs and charts for PMs and admins."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.deps import get_current_user
from app.models import Task, TaskStatus, TaskStatusHistory, User
from app.reports.metrics import MetricFilters, Metrics, default_period
from app.services import time_tracking
from app.services.projects import visible_project_ids
from app.services.tasks import TaskFilters, search_tasks
from app.templating import render

router = APIRouter(include_in_schema=False)


@router.get("/")
def dashboard(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    my_open = [t for t in search_tasks(db, user, TaskFilters(assignee_id=user.id, sort="due"))
               if t.status != TaskStatus.DONE]
    timesheet = time_tracking.build_timesheet(db, user, today)
    ids = visible_project_ids(db, user)
    activity_query = (
        select(TaskStatusHistory)
        .options(joinedload(TaskStatusHistory.task).joinedload(Task.project), joinedload(TaskStatusHistory.changed_by))
        .join(Task).order_by(TaskStatusHistory.changed_at.desc(), TaskStatusHistory.id.desc()).limit(8)
    )
    if ids is not None:
        activity_query = activity_query.where(Task.project_id.in_(ids))
    context = {
        "my_open": my_open[:8],
        "my_open_count": len(my_open),
        "due_soon": [t for t in my_open if t.due_date and t.due_date <= today + timedelta(days=7)],
        "overdue_mine": [t for t in my_open if t.is_overdue],
        "timesheet": timesheet,
        "timer": time_tracking.running_timer(db, user),
        "activity": list(db.scalars(activity_query)),
    }
    if user.is_manager:
        start, end = default_period(today, weeks=6)
        metrics = Metrics(db, user, MetricFilters(start=start, end=end))
        context.update(
            summary=metrics.summary(),
            charts={k: v for k, v in metrics.charts().items() if k in ("hours_by_week", "completed_by_week", "status")},
            utilisation=metrics.utilisation(),
            overdue=metrics.overdue_tasks(limit=6),
            period=(start, end),
        )
    return render(request, "dashboard.html", context)

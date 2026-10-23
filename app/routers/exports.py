"""Download tasks, time entries, requirements, test cases and the metrics report as
CSV, Excel or PDF. Every export honours the same filters as the page it came from."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.reports.exporters import MEDIA_TYPES, filename, render, sections_to_pdf, sections_to_xlsx
from app.reports.tables import requirements_table, tasks_table, test_cases_table, time_entries_table
from app.reports.weekly import build_sections
from app.routers.forms import to_date, to_int
from app.routers.reports import metric_filters
from app.routers.tasks import filter_dependency
from app.services import requirements as requirement_service
from app.services import time_tracking
from app.services.audit import record
from app.services.errors import NotFound, ServiceError
from app.services.tasks import TaskFilters, search_tasks

router = APIRouter(prefix="/exports", tags=["exports"])

MAX_ROWS = 20000


def _file(data: bytes, base: str, fmt: str) -> Response:
    return Response(data, media_type=MEDIA_TYPES[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{filename(base, fmt)}"',
                             "Cache-Control": "no-store"})


def _check(fmt: str) -> None:
    if fmt not in MEDIA_TYPES:
        raise NotFound("Export format must be csv, xlsx or pdf.")


@router.get("/tasks.{fmt}", summary="Export tasks")
def export_tasks(request: Request, fmt: str, filters: TaskFilters = Depends(filter_dependency),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(fmt)
    tasks = search_tasks(db, user, filters, limit=MAX_ROWS)
    record(db, "export.tasks", user=user, details={"format": fmt, "rows": len(tasks), **filters.as_query()},
           request=request)
    db.commit()
    return _file(render(tasks_table(tasks), fmt), "tasks", fmt)


@router.get("/time.{fmt}", summary="Export time entries")
def export_time(request: Request, fmt: str, start: str | None = None, end: str | None = None,
                week: str | None = None, user_id: str | None = None, project_id: str | None = None,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(fmt)
    if week:
        first = time_tracking.week_start(to_date(week) or date.today())
        first_day, last_day = first, first + timedelta(days=6)
    else:
        last_day = to_date(end) or date.today()
        first_day = to_date(start) or last_day - timedelta(days=27)
    if last_day < first_day:
        raise ServiceError("End date must be on or after the start date.")
    entries = time_tracking.entries_between(db, user, first_day, last_day, to_int(user_id), to_int(project_id))
    record(db, "export.time", user=user, details={"format": fmt, "rows": len(entries)}, request=request)
    db.commit()
    return _file(render(time_entries_table(entries, first_day, last_day), fmt), "time-entries", fmt)


@router.get("/requirements.{fmt}", summary="Export requirements with acceptance criteria")
def export_requirements(fmt: str, project_id: str | None = None, task_id: str | None = None, q: str | None = None,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(fmt)
    requirements = requirement_service.list_requirements(db, user, to_int(project_id), to_int(task_id), q)
    return _file(render(requirements_table(requirements), fmt), "requirements", fmt)


@router.get("/test-cases.{fmt}", summary="Export test cases")
def export_test_cases(fmt: str, project_id: str | None = None, task_id: str | None = None,
                      requirement_id: list[int] | None = Query(None),
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(fmt)
    requirements = requirement_service.list_requirements(db, user, to_int(project_id), to_int(task_id))
    if requirement_id:
        requirements = [r for r in requirements if r.id in requirement_id]
    return _file(render(test_cases_table(requirements), fmt), "test-cases", fmt)


@router.get("/report.{fmt}", summary="Export the metrics report for a period")
def export_report(request: Request, fmt: str, start: str | None = None, end: str | None = None,
                  project_id: str | None = None, user_id: str | None = None,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if fmt not in ("pdf", "xlsx"):
        raise NotFound("Reports export as pdf or xlsx.")
    filters = metric_filters(start, end, project_id, user_id, user)
    sections, _ = build_sections(db, user, filters.start, filters.end, filters.project_id, filters.user_id)
    title = f"Delivery report · {filters.start:%d %b} – {filters.end:%d %b %Y}"
    subtitle = f"Prepared for {user.full_name}"
    data = sections_to_pdf(title, subtitle, sections) if fmt == "pdf" else sections_to_xlsx(title, sections)
    record(db, "export.report", user=user, details={"format": fmt}, request=request)
    db.commit()
    return _file(data, "report", fmt)

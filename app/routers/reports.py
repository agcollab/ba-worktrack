"""Reports: the metrics dashboard with filters and the weekly PDF / Excel reports."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from app.database import get_db
from app.deps import csrf_protect, get_current_user, require_manager
from app.models import GeneratedReport, User
from app.reports.exporters import MEDIA_TYPES
from app.reports.metrics import MetricFilters, Metrics, default_period
from app.reports.weekly import generate_weekly_report, previous_week
from app.routers.forms import redirect, to_date, to_int
from app.services import projects as project_service
from app.services.errors import NotFound, ServiceError
from app.services.users import list_users
from app.templating import render

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(csrf_protect)], include_in_schema=False)


def metric_filters(start: str | None, end: str | None, project_id: str | None, user_id: str | None,
                   viewer: User) -> MetricFilters:
    default_start, default_end = default_period()
    filters = MetricFilters(start=to_date(start) or default_start, end=to_date(end) or default_end,
                            project_id=to_int(project_id), user_id=to_int(user_id))
    if not viewer.is_manager:
        filters.user_id = viewer.id  # BAs see their own numbers only
    if filters.end < filters.start:
        raise ServiceError("End date must be on or after the start date.")
    if (filters.end - filters.start).days > 366:
        raise ServiceError("Choose a period of one year or less.")
    return filters


@router.get("")
def reports_page(request: Request, start: str | None = None, end: str | None = None, project_id: str | None = None,
                 user_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    filters = metric_filters(start, end, project_id, user_id, user)
    metrics = Metrics(db, user, filters)
    reports = []
    if user.is_manager:
        reports = db.scalars(select(GeneratedReport).order_by(GeneratedReport.id.desc()).limit(20)).all()
    week_start, week_end = previous_week()
    return render(request, "reports/index.html", {
        "filters": filters, "summary": metrics.summary(), "charts": metrics.charts(),
        "utilisation": metrics.utilisation(), "overdue": metrics.overdue_tasks(), "reports": reports,
        "projects": project_service.list_projects(db, user), "people": list_users(db, include_inactive=False),
        "fq": {"start": filters.start, "end": filters.end, "project_id": filters.project_id,
               "user_id": filters.user_id if user.is_manager else None},
        "week_start": week_start, "presets": _presets(),
    })


def _presets() -> list[tuple[str, date, date]]:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    first_of_month = today.replace(day=1)
    last_month_end = first_of_month - timedelta(days=1)
    return [
        ("This week", monday, today),
        ("Last week", monday - timedelta(weeks=1), monday - timedelta(days=1)),
        ("Last 4 weeks", monday - timedelta(weeks=3), today),
        ("This month", first_of_month, today),
        ("Last month", last_month_end.replace(day=1), last_month_end),
        ("Quarter to date", date(today.year, 3 * ((today.month - 1) // 3) + 1, 1), today),
    ]


@router.post("/weekly")
def create_weekly(week_start: str = Form(""), project_id: str = Form(""), user: User = Depends(require_manager),
                  db: Session = Depends(get_db)):
    start = to_date(week_start) or previous_week()[0]
    start = start - timedelta(days=start.weekday())
    report = generate_weekly_report(db, user, start, project_id=to_int(project_id))
    db.commit()
    return redirect("/reports#weekly", f"Created: {report.title}.")


@router.get("/{report_id}/download.{fmt}")
def download_report(report_id: int, fmt: str, user: User = Depends(require_manager), db: Session = Depends(get_db)):
    if fmt not in ("pdf", "xlsx"):
        raise NotFound("Unknown format.")
    report = db.scalar(select(GeneratedReport).options(undefer(GeneratedReport.pdf_data), undefer(GeneratedReport.xlsx_data))
                       .where(GeneratedReport.id == report_id))
    if report is None:
        raise NotFound("Report not found.")
    data = report.pdf_data if fmt == "pdf" else report.xlsx_data
    if not data:
        raise NotFound("This report has no file in that format.")
    name = f"weekly-report-{report.period_start:%Y%m%d}.{fmt}"
    return Response(data, media_type=MEDIA_TYPES[fmt], headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/{report_id}/delete")
def delete_report(report_id: int, user: User = Depends(require_manager), db: Session = Depends(get_db)):
    report = db.get(GeneratedReport, report_id)
    if report is None:
        raise NotFound("Report not found.")
    db.delete(report)
    db.commit()
    return redirect("/reports#weekly", "Report deleted.")

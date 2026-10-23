"""Metrics match hand-written SQL, and the weekly report produces PDF + Excel."""
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from app.models import GeneratedReport, TaskStatus, TaskStatusHistory, TimeEntry
from app.reports.metrics import MetricFilters, Metrics
from app.reports.weekly import generate_weekly_report, previous_week
from app.services import tasks as task_service
from app.services import time_tracking
from tests.conftest import form, login


def build(db, people):
    today = date.today()
    a = task_service.create_task(db, people["pm"], people["pay"].id, "A", assignee_id=people["asha"].id, estimate_hours=4)
    b = task_service.create_task(db, people["pm"], people["crm"].id, "B", assignee_id=people["ben"].id, estimate_hours=2)
    for status in (TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW, TaskStatus.DONE):
        task_service.change_status(db, people["asha"], a, status)
    time_tracking.log_time(db, people["asha"], a, today, 5)
    time_tracking.log_time(db, people["ben"], b, today, 3)
    b.due_date = today - timedelta(days=2)
    db.commit()
    return a, b


def test_metrics_match_sql(db, people):
    build(db, people)
    today = date.today()
    metrics = Metrics(db, people["pm"], MetricFilters(start=today - timedelta(days=6), end=today))
    by_sql = db.scalar(select(func.sum(TimeEntry.hours)))
    assert metrics.total_hours() == by_sql == 8
    assert metrics.tasks_completed() == 1
    assert metrics.overdue_count() == 1
    assert metrics.estimate_vs_actual()["ratio"] == 1.25  # 5 h actual / 4 h estimate
    assert dict(metrics.hours_by_project()) == {"CRM": 3, "PAY": 5}
    done_rows = db.scalar(select(func.count()).select_from(TaskStatusHistory).where(
        TaskStatusHistory.to_status == TaskStatus.DONE))
    assert done_rows == 1


def test_ba_metrics_only_cover_their_projects(db, people):
    build(db, people)
    today = date.today()
    metrics = Metrics(db, people["asha"], MetricFilters(start=today - timedelta(days=6), end=today))
    assert metrics.total_hours() == 5


def test_cycle_time(db, people):
    a, _ = build(db, people)
    rows = db.query(TaskStatusHistory).filter_by(task_id=a.id).order_by(TaskStatusHistory.id).all()
    rows[1].changed_at = datetime.now() - timedelta(days=3)  # moved to In Progress 3 days ago
    db.commit()
    today = date.today()
    metrics = Metrics(db, people["pm"], MetricFilters(start=today - timedelta(days=6), end=today))
    assert 2.9 <= metrics.cycle_time_days() <= 3.1


def test_weekly_report_files(db, people):
    build(db, people)
    start = date.today() - timedelta(days=date.today().weekday())
    report = generate_weekly_report(db, people["pm"], start)
    db.commit()
    assert report.pdf_data.startswith(b"%PDF")
    assert report.xlsx_data[:2] == b"PK"  # xlsx files are zip archives


def test_scheduled_report_has_no_author(db, people):
    build(db, people)
    start, end = previous_week()
    report = generate_weekly_report(db, None, start, end)
    assert report.created_by_id is None and (end - start).days == 6


def test_reports_page_and_downloads(client, db, people):
    build(db, people)
    login(client, "pm@test.com")
    assert client.get("/reports").status_code == 200
    client.post("/reports/weekly", data=form(client))
    report = db.query(GeneratedReport).one()
    assert client.get(f"/reports/{report.id}/download.pdf").content.startswith(b"%PDF")
    assert client.get(f"/reports/{report.id}/download.xlsx").status_code == 200


def test_ba_sees_reports_but_not_weekly_files(client, db, people):
    build(db, people)
    login(client, "asha@test.com")
    assert client.get("/reports").status_code == 200
    assert client.post("/reports/weekly", data=form(client)).status_code == 403

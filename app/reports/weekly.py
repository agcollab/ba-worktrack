"""The weekly report: KPIs, hours, completed work, overdue tasks and a short narrative.

Built on demand from the Reports page, and every Friday by the scheduler.
"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import GeneratedReport, Project, Task, User
from app.reports.exporters import ExportTable, ReportSection, sections_to_pdf, sections_to_xlsx
from app.reports.metrics import MetricFilters, Metrics


def _fmt(value, suffix: str = "") -> str:
    return "–" if value is None else f"{value:g}{suffix}"


def narrative(summary: dict, utilisation: list[dict], overdue: list[Task]) -> str:
    """A plain-English summary a PM can paste into an email."""
    lines = [
        f"The team logged {summary['total_hours']:g} hours and completed {summary['tasks_completed']} "
        f"task{'s' if summary['tasks_completed'] != 1 else ''}; {summary['open_tasks']} remain open."
    ]
    if summary["utilisation_percent"] is not None:
        lines.append(f"Overall utilisation was {summary['utilisation_percent']:g}% of capacity.")
    over = [u for u in utilisation if u["percent"] > 100]
    under = [u for u in utilisation if u["percent"] < 50]
    if over:
        lines.append("Over capacity: " + ", ".join(f"{u['user'].full_name} ({u['percent']:g}%)" for u in over) + ".")
    if under:
        lines.append("Below 50% logged: " + ", ".join(u["user"].full_name for u in under) +
                     " – check for missing timesheets.")
    ratio = summary["estimate_vs_actual"]["ratio"]
    if ratio is not None:
        direction = "over" if ratio > 1 else "under"
        lines.append(f"Completed work took {ratio:g}x its estimate ({abs(ratio - 1) * 100:.0f}% {direction}).")
    if summary["cycle_time_days"] is not None:
        lines.append(f"Average cycle time was {summary['cycle_time_days']:g} days.")
    if overdue:
        lines.append(f"{summary['overdue']} task{'s are' if summary['overdue'] != 1 else ' is'} overdue; "
                     f"the oldest is {overdue[0].key} (due {overdue[0].due_date:%d %b}).")
    else:
        lines.append("No tasks are overdue.")
    return " ".join(lines)


def build_sections(db: Session, viewer: User | None, start: date, end: date,
                   project_id: int | None = None, user_id: int | None = None) -> tuple[list[ReportSection], dict]:
    metrics = Metrics(db, viewer, MetricFilters(start=start, end=end, project_id=project_id, user_id=user_id))
    summary = metrics.summary()
    utilisation = metrics.utilisation()
    overdue = metrics.overdue_tasks(limit=50)
    eva = summary["estimate_vs_actual"]

    completed_ids = [row[0] for row in db.execute(metrics._done_in_period())]
    completed = db.scalars(
        select(Task).options(joinedload(Task.project), joinedload(Task.assignee)).where(Task.id.in_(completed_ids))
        .order_by(Task.project_id, Task.id)
    ).all() if completed_ids else []

    users, projects, grid = metrics.hours_by_user_and_project()
    hours_rows = [[u] + [grid.get((u, p), 0) for p in projects] + [round(sum(grid.get((u, p), 0) for p in projects), 1)]
                  for u in users]
    hours_totals = ["Total"] + [round(sum(grid.get((u, p), 0) for u in users), 1) for p in projects] + \
                   [round(sum(grid.values()), 1)]

    sections = [
        ReportSection(
            heading="Summary",
            kpis=[
                ("Hours logged", _fmt(summary["total_hours"])),
                ("Tasks completed", str(summary["tasks_completed"])),
                ("Open tasks", str(summary["open_tasks"])),
                ("Overdue tasks", str(summary["overdue"])),
                ("Utilisation", _fmt(summary["utilisation_percent"], "%")),
                ("Avg cycle time", _fmt(summary["cycle_time_days"], " d")),
                ("Actual / estimate", _fmt(eva["ratio"], "x")),
                ("AI adoption", _fmt(summary["ai"]["rate"], "%")),
            ],
            text=narrative(summary, utilisation, overdue),
        ),
        ReportSection(
            heading="Hours by person and project",
            table=ExportTable(title="", columns=["Person"] + projects + ["Total"], rows=hours_rows,
                              totals=hours_totals if hours_rows else None, sheet_name="Hours"),
        ),
        ReportSection(
            heading="Utilisation",
            table=ExportTable(
                title="", columns=["Person", "Hours", "Capacity", "Utilisation %"],
                rows=[[u["user"].full_name, u["hours"], u["capacity"], u["percent"]] for u in utilisation],
                sheet_name="Utilisation",
            ),
        ),
        ReportSection(
            heading=f"Completed tasks ({len(completed)})",
            table=ExportTable(
                title="", columns=["Key", "Title", "Project", "Assignee", "Estimate h", "Actual h"],
                rows=[[t.key, t.title, t.project.key, t.assignee.full_name if t.assignee else "", t.estimate_hours,
                       t.total_hours] for t in completed],
                pdf_widths=[8, 40, 8, 16, 8, 8], sheet_name="Completed",
            ),
        ),
        ReportSection(
            heading=f"Overdue tasks ({summary['overdue']})",
            table=ExportTable(
                title="", columns=["Key", "Title", "Status", "Assignee", "Due", "Days late"],
                rows=[[t.key, t.title, str(t.status), t.assignee.full_name if t.assignee else "Unassigned",
                       t.due_date, (date.today() - t.due_date).days] for t in overdue],
                pdf_widths=[8, 40, 10, 16, 9, 7], sheet_name="Overdue",
            ),
        ),
    ]
    return sections, summary


def previous_week(today: date | None = None) -> tuple[date, date]:
    """Mon-Sun of the current week if today is Fri-Sun, else of last week."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    if today.weekday() < 4:
        monday -= timedelta(weeks=1)
    return monday, monday + timedelta(days=6)


def generate_weekly_report(db: Session, viewer: User | None, start: date, end: date | None = None,
                           project_id: int | None = None) -> GeneratedReport:
    end = end or start + timedelta(days=6)
    project = db.get(Project, project_id) if project_id else None
    scope = project.name if project else "All projects"
    title = f"Weekly report · {start:%d %b} – {end:%d %b %Y}"
    subtitle = f"{scope} · prepared for {viewer.full_name if viewer else 'the team'}"
    sections, _ = build_sections(db, viewer, start, end, project_id)
    report = GeneratedReport(
        kind="weekly",
        title=f"{title} · {scope}",
        period_start=start,
        period_end=end,
        project_id=project_id,
        pdf_data=sections_to_pdf(title, subtitle, sections),
        xlsx_data=sections_to_xlsx(title, sections),
        created_by_id=viewer.id if viewer else None,
    )
    db.add(report)
    db.flush()
    return report


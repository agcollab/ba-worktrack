"""Build ExportTables for the things users export: tasks, time entries, requirements."""
from datetime import date

from app.models import Requirement, Task, TimeEntry
from app.reports.exporters import ExportTable
from app.services.requirements import format_criterion


def tasks_table(tasks: list[Task], subtitle: str | None = None) -> ExportTable:
    rows = [
        [
            t.key, t.title, t.project.name if t.project else "", str(t.status), str(t.priority),
            t.type_label, t.assignee.full_name if t.assignee else "Unassigned",
            t.due_date, t.estimate_hours, t.total_hours,
            "Yes" if t.is_overdue else "", (t.external_source or "").upper(), t.external_id or "",
            t.created_at, t.updated_at,
        ]
        for t in tasks
    ]
    return ExportTable(
        title="Tasks",
        subtitle=subtitle or f"{len(tasks)} tasks · exported {date.today():%d %b %Y}",
        columns=["Key", "Title", "Project", "Status", "Priority", "Type", "Assignee", "Due",
                 "Estimate h", "Logged h", "Overdue", "Source", "External ID", "Created", "Updated"],
        rows=rows,
        pdf_widths=[7, 28, 13, 9, 7, 9, 12, 8, 6, 6, 6, 6, 8, 10, 10],
        sheet_name="Tasks",
        totals=["Total", "", "", "", "", "", "", "",
                round(sum(t.estimate_hours or 0 for t in tasks), 1), round(sum(t.total_hours for t in tasks), 1),
                "", "", "", "", ""],
    )


def time_entries_table(entries: list[TimeEntry], start: date, end: date) -> ExportTable:
    rows = [
        [e.work_date, e.user.full_name, e.task.project.key, e.task.key, e.task.title, str(e.task.task_type),
         e.hours, e.note or ""]
        for e in entries
    ]
    return ExportTable(
        title="Time entries",
        subtitle=f"{start:%d %b %Y} – {end:%d %b %Y} · {len(entries)} entries",
        columns=["Date", "User", "Project", "Task", "Task title", "Type", "Hours", "Note"],
        rows=rows,
        pdf_widths=[9, 14, 7, 8, 30, 10, 6, 26],
        sheet_name="Time entries",
        totals=["Total", "", "", "", "", "", round(sum(e.hours for e in entries), 2), ""],
    )


def requirements_table(requirements: list[Requirement]) -> ExportTable:
    rows = []
    for r in requirements:
        criteria = "\n\n".join(f"AC{c.position}: " + format_criterion(c) for c in r.criteria)
        tests = "\n".join(f"• {tc.title} [{tc.status}]" for tc in r.test_cases)
        rows.append([f"REQ-{r.id}", r.project.key, r.title, r.kind, r.status, r.source,
                     r.task.key if r.task else "", r.description or "", criteria, tests])
    return ExportTable(
        title="Requirements",
        subtitle=f"{len(requirements)} requirements · exported {date.today():%d %b %Y}",
        columns=["ID", "Project", "Title", "Kind", "Status", "Source", "Task", "Description",
                 "Acceptance criteria", "Test cases"],
        rows=rows,
        pdf_widths=[6, 6, 16, 8, 7, 6, 7, 20, 26, 16],
        sheet_name="Requirements",
    )


def test_cases_table(requirements: list[Requirement]) -> ExportTable:
    rows = [
        [f"TC-{tc.id}", f"REQ-{r.id}", r.title, tc.title, tc.preconditions or "", tc.steps, tc.expected_result,
         str(tc.priority), str(tc.status)]
        for r in requirements for tc in r.test_cases
    ]
    return ExportTable(
        title="Test cases",
        columns=["ID", "Requirement", "Requirement title", "Test case", "Preconditions", "Steps",
                 "Expected result", "Priority", "Status"],
        rows=rows,
        pdf_widths=[6, 8, 14, 16, 14, 26, 18, 7, 7],
        sheet_name="Test cases",
    )

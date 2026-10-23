"""The database layer: tables, constraints, relationships."""
from datetime import date

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError, StatementError

from app.models import Project, Role, Task, TaskStatus, TaskType, TimeEntry, User


def make_user(email: str = "asha@test.com", name: str = "Asha Rao") -> User:
    return User(email=email, full_name=name, hashed_password="not-a-real-hash")


def make_task_with_hours(db) -> Task:
    """One project, one BA, one task with three time entries (6.5 h in total)."""
    ba = make_user()
    project = Project(key="PAY", name="Payments")
    task = Task(project=project, title="Write UAC for refunds", task_type=TaskType.UAC, assignee=ba)
    task.time_entries = [
        TimeEntry(user=ba, work_date=date(2026, 10, 12), hours=2.5),
        TimeEntry(user=ba, work_date=date(2026, 10, 13), hours=3),
        TimeEntry(user=ba, work_date=date(2026, 10, 14), hours=1, note="Review"),
    ]
    db.add(task)
    db.commit()
    return task


def test_all_tables_are_created(engine):
    tables = set(inspect(engine).get_table_names())
    expected = {
        "users", "roles", "user_roles", "projects", "project_members", "tasks",
        "task_status_history", "task_comments", "attachments", "time_entries",
        "requirements", "acceptance_criteria", "test_cases", "ai_generation_logs",
        "integrations", "integration_mappings", "audit_logs", "sync_logs", "running_timers",
        "generated_reports",
    }
    assert expected <= tables


def test_task_with_time_entries(db):
    task = make_task_with_hours(db)

    saved = db.get(Task, task.id)
    assert saved.status == TaskStatus.TODO  # the default
    assert saved.project.key == "PAY"
    assert saved.assignee.full_name == "Asha Rao"
    assert len(saved.time_entries) == 3
    assert saved.total_hours == 6.5
    assert saved.created_at is not None  # filled in by the database


def test_sum_hours_with_sql(db):
    """The same total, worked out by the database with SUM + GROUP BY."""
    make_task_with_hours(db)
    rows = db.execute(
        select(User.full_name, func.sum(TimeEntry.hours))
        .join(TimeEntry.user)
        .group_by(User.full_name)
    ).all()
    assert rows == [("Asha Rao", 6.5)]


def test_status_is_stored_as_readable_text(db):
    task = make_task_with_hours(db)
    task.status = TaskStatus.IN_PROGRESS
    db.commit()
    raw = db.execute(select(Task.__table__.c.status)).scalar_one()
    assert raw == "In Progress"


def test_unknown_status_is_rejected(db):
    project = Project(key="X", name="X")
    db.add(Task(project=project, title="Bad", status="Finished"))
    with pytest.raises(StatementError):
        db.commit()


def test_hours_must_be_between_0_and_24(db):
    task = make_task_with_hours(db)
    db.add(TimeEntry(user=task.assignee, task=task, work_date=date(2026, 10, 15), hours=30))
    with pytest.raises(IntegrityError):  # CHECK constraint failed
        db.commit()


def test_time_entry_needs_a_real_task(db):
    user = make_user()
    db.add(user)
    db.commit()
    db.add(TimeEntry(user_id=user.id, task_id=999, work_date=date(2026, 10, 15), hours=1))
    with pytest.raises(IntegrityError):  # FOREIGN KEY constraint failed
        db.commit()


def test_email_must_be_unique(db):
    db.add_all([make_user(), make_user(name="Someone Else")])
    with pytest.raises(IntegrityError):  # UNIQUE constraint failed: users.email
        db.commit()


def test_user_can_have_several_roles(db):
    ba, admin = Role(name="BA"), Role(name="Admin")
    user = make_user()
    user.roles = [ba, admin]
    db.add(user)
    db.commit()

    assert sorted(user.role_names) == ["Admin", "BA"]
    assert user.has_role("Admin")
    assert not user.has_role("PM")
    assert [u.email for u in ba.users] == ["asha@test.com"]  # works from the other side too


def test_deleting_a_task_deletes_its_time_entries(db):
    task = make_task_with_hours(db)
    db.delete(task)
    db.commit()
    assert db.scalar(select(func.count()).select_from(TimeEntry)) == 0
    assert db.scalar(select(func.count()).select_from(User)) == 1  # the user stays

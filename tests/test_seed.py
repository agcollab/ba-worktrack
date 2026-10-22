"""The seed script, run against the in-memory test database."""
from datetime import date, timedelta

from sqlalchemy import func, select

from app.models import Project, Task, TaskStatus, TimeEntry, User
from app.security import verify_password
from scripts.seed import DEMO_PASSWORD, seed

TODAY = date(2026, 10, 19)


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def test_seed_creates_the_demo_data(db):
    counts = seed(db, today=TODAY)

    assert counts == {"users": 7, "projects": 2, "tasks": 50, "time_entries": 200, "requirements": 8}
    assert count(db, User) == 7
    assert count(db, Project) == 2
    assert count(db, Task) == 50
    assert count(db, TimeEntry) == 200


def test_seeded_admin_can_use_the_demo_password(db):
    seed(db, today=TODAY)
    admin = db.scalar(select(User).where(User.email == "admin@demo.com"))
    assert admin.has_role("Admin")
    assert admin.hashed_password != DEMO_PASSWORD  # stored hashed, not as plain text
    assert verify_password(DEMO_PASSWORD, admin.hashed_password)


def test_seeded_hours_are_realistic(db):
    seed(db, today=TODAY)
    entries = db.scalars(select(TimeEntry)).all()

    six_weeks_ago = TODAY - timedelta(weeks=6)
    assert all(six_weeks_ago <= e.work_date <= TODAY for e in entries)
    assert all(e.work_date.weekday() < 5 for e in entries)  # no weekends

    # nobody logs more than 9 hours in one day
    daily = db.execute(
        select(TimeEntry.user_id, TimeEntry.work_date, func.sum(TimeEntry.hours))
        .group_by(TimeEntry.user_id, TimeEntry.work_date)
    ).all()
    assert max(total for _, _, total in daily) <= 9

    # no hours on tasks that were never started
    todo_hours = db.scalar(
        select(func.count()).select_from(TimeEntry).join(TimeEntry.task).where(Task.status == TaskStatus.TODO)
    )
    assert todo_hours == 0


def test_status_history_ends_at_the_current_status(db):
    seed(db, today=TODAY)
    for task in db.scalars(select(Task)).all():
        assert task.status_history[0].to_status == TaskStatus.TODO
        assert task.status_history[-1].to_status == task.status

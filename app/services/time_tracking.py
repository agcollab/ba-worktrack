"""Time tracking: manual entries, a start/stop timer and the weekly timesheet grid."""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import RunningTimer, Task, TimeEntry, User
from app.services.errors import Forbidden, NotFound, ServiceError

MAX_HOURS_PER_DAY = 24.0
MAX_DAYS_BACK = 90


def week_start(day: date) -> date:
    """Monday of the week that contains day."""
    return day - timedelta(days=day.weekday())


def hours_on_day(db: Session, user_id: int, day: date, exclude_id: int | None = None) -> float:
    query = select(func.coalesce(func.sum(TimeEntry.hours), 0.0)).where(
        TimeEntry.user_id == user_id, TimeEntry.work_date == day
    )
    if exclude_id:
        query = query.where(TimeEntry.id != exclude_id)
    return float(db.scalar(query) or 0)


def _validate(db: Session, user_id: int, work_date: date, hours: float, exclude_id: int | None = None) -> None:
    if hours is None or hours <= 0:
        raise ServiceError("Hours must be more than 0.")
    if hours > MAX_HOURS_PER_DAY:
        raise ServiceError("A single entry can't be more than 24 hours.")
    if work_date > date.today():
        raise ServiceError("You can't log time in the future.")
    if work_date < date.today() - timedelta(days=MAX_DAYS_BACK):
        raise ServiceError(f"Entries older than {MAX_DAYS_BACK} days are locked.")
    already = hours_on_day(db, user_id, work_date, exclude_id)
    if already + hours > MAX_HOURS_PER_DAY:
        left = max(0.0, MAX_HOURS_PER_DAY - already)
        raise ServiceError(f"That makes more than 24 h on {work_date:%d %b}. You can add up to {left:g} h.")


def log_time(db: Session, user: User, task: Task, work_date: date, hours: float, note: str | None = None) -> TimeEntry:
    hours = round(float(hours), 2)
    _validate(db, user.id, work_date, hours)
    entry = TimeEntry(user_id=user.id, task_id=task.id, work_date=work_date, hours=hours,
                      note=(note or "").strip()[:500] or None)
    db.add(entry)
    db.flush()
    return entry


def get_entry(db: Session, user: User, entry_id: int) -> TimeEntry:
    entry = db.get(TimeEntry, entry_id)
    if entry is None:
        raise NotFound("Time entry not found.")
    if entry.user_id != user.id and not user.is_manager:
        raise Forbidden("You can only change your own time entries.")
    return entry


def update_entry(db: Session, user: User, entry: TimeEntry, work_date: date, hours: float, note: str | None) -> None:
    if entry.user_id != user.id and not user.is_manager:
        raise Forbidden("You can only change your own time entries.")
    hours = round(float(hours), 2)
    _validate(db, entry.user_id, work_date, hours, exclude_id=entry.id)
    entry.work_date, entry.hours = work_date, hours
    entry.note = (note or "").strip()[:500] or None
    db.flush()


def delete_entry(db: Session, user: User, entry: TimeEntry) -> None:
    if entry.user_id != user.id and not user.is_manager:
        raise Forbidden("You can only delete your own time entries.")
    db.delete(entry)
    db.flush()


# ---- timer ------------------------------------------------------------------

def running_timer(db: Session, user: User) -> RunningTimer | None:
    return db.scalar(
        select(RunningTimer).options(joinedload(RunningTimer.task).joinedload(Task.project))
        .where(RunningTimer.user_id == user.id)
    )


def start_timer(db: Session, user: User, task: Task, note: str | None = None) -> tuple[RunningTimer, TimeEntry | None]:
    """Start a timer on task. A timer already running on another task is stopped first."""
    stopped = None
    current = running_timer(db, user)
    if current is not None:
        if current.task_id == task.id:
            return current, None
        stopped = stop_timer(db, user)
    timer = RunningTimer(user_id=user.id, task_id=task.id, started_at=datetime.now(), note=note)
    db.add(timer)
    db.flush()
    return timer, stopped


def stop_timer(db: Session, user: User) -> TimeEntry | None:
    """Stop the timer and log its time (rounded to 0.05 h, minimum 0.05 h).

    Returns None if the timer ran less than a minute.
    """
    timer = running_timer(db, user)
    if timer is None:
        raise ServiceError("No timer is running.")
    elapsed_hours = (datetime.now() - timer.started_at).total_seconds() / 3600
    task_id, note, started = timer.task_id, timer.note, timer.started_at
    db.delete(timer)
    db.flush()
    if elapsed_hours < 1 / 60:
        return None
    hours = min(MAX_HOURS_PER_DAY, max(0.05, round(elapsed_hours * 20) / 20))
    day = started.date()
    room = MAX_HOURS_PER_DAY - hours_on_day(db, user.id, day)
    hours = round(min(hours, room), 2)
    if hours <= 0:
        raise ServiceError(f"{day:%d %b} already has 24 h logged; timer discarded.")
    entry = TimeEntry(user_id=user.id, task_id=task_id, work_date=day, hours=hours, note=note or "Timer")
    db.add(entry)
    db.flush()
    return entry


# ---- weekly timesheet ---------------------------------------------------------

@dataclass
class TimesheetRow:
    task: Task
    hours: dict[date, float] = field(default_factory=dict)
    entries: dict[date, list[TimeEntry]] = field(default_factory=dict)

    @property
    def total(self) -> float:
        return round(sum(self.hours.values()), 2)


@dataclass
class Timesheet:
    user: User
    start: date
    days: list[date]
    rows: list[TimesheetRow]

    @property
    def day_totals(self) -> dict[date, float]:
        return {d: round(sum(r.hours.get(d, 0) for r in self.rows), 2) for d in self.days}

    @property
    def total(self) -> float:
        return round(sum(self.day_totals.values()), 2)

    @property
    def utilisation(self) -> float:
        capacity = self.user.weekly_capacity_hours or 40
        return round(self.total / capacity * 100, 1)


def build_timesheet(db: Session, user: User, start: date) -> Timesheet:
    start = week_start(start)
    days = [start + timedelta(days=i) for i in range(7)]
    entries = db.scalars(
        select(TimeEntry)
        .options(joinedload(TimeEntry.task).joinedload(Task.project))
        .where(TimeEntry.user_id == user.id, TimeEntry.work_date >= days[0], TimeEntry.work_date <= days[-1])
        .order_by(TimeEntry.work_date, TimeEntry.id)
    )
    rows: dict[int, TimesheetRow] = {}
    for entry in entries:
        row = rows.setdefault(entry.task_id, TimesheetRow(task=entry.task))
        row.hours[entry.work_date] = round(row.hours.get(entry.work_date, 0) + entry.hours, 2)
        row.entries.setdefault(entry.work_date, []).append(entry)
    ordered = sorted(rows.values(), key=lambda r: (r.task.project.key, r.task.id))
    return Timesheet(user=user, start=start, days=days, rows=ordered)


def entries_between(db: Session, user: User, start: date, end: date, user_id: int | None = None,
                    project_id: int | None = None) -> list[TimeEntry]:
    """Time entries for export. BAs only ever get their own."""
    query = (
        select(TimeEntry)
        .options(joinedload(TimeEntry.task).joinedload(Task.project), joinedload(TimeEntry.user))
        .where(TimeEntry.work_date >= start, TimeEntry.work_date <= end)
        .order_by(TimeEntry.work_date, TimeEntry.id)
    )
    if not user.is_manager:
        query = query.where(TimeEntry.user_id == user.id)
    elif user_id:
        query = query.where(TimeEntry.user_id == user_id)
    if project_id:
        query = query.join(Task).where(Task.project_id == project_id)
    return list(db.scalars(query))

"""Metric definitions. Every number on the dashboards and reports comes from here.

| Metric               | Formula                                                              |
|----------------------|----------------------------------------------------------------------|
| Hours logged         | SUM(time_entries.hours) in the period                                |
| Tasks completed      | tasks whose status moved to Done in the period (status history)      |
| Cycle time (days)    | first move to In Progress -> last move to Done, averaged             |
| Estimate vs actual   | SUM(actual hours) / SUM(estimate) for tasks completed in the period   |
| Utilisation %        | hours logged / (weekly capacity x weeks in period) x 100             |
| Overdue tasks        | due_date < today AND status <> Done                                  |
| AI adoption %        | AI generations accepted or edited / AI generations reviewed x 100    |
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    AIGenerationLog,
    Project,
    Requirement,
    Task,
    TaskStatus,
    TaskStatusHistory,
    TimeEntry,
    User,
)
from app.services.projects import visible_project_ids


@dataclass
class MetricFilters:
    start: date
    end: date
    project_id: int | None = None
    user_id: int | None = None

    @property
    def weeks(self) -> float:
        return max(1.0, ((self.end - self.start).days + 1) / 7)

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.start, time.min)

    @property
    def end_dt(self) -> datetime:
        return datetime.combine(self.end, time.max)


def default_period(today: date | None = None, weeks: int = 4) -> tuple[date, date]:
    today = today or date.today()
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    return start, today


class Metrics:
    """Computes metrics for one user's view (BAs only see their projects)."""

    def __init__(self, db: Session, viewer: User | None, filters: MetricFilters):
        """viewer=None means the system (scheduled jobs): every project."""
        self.db = db
        self.viewer = viewer
        self.f = filters
        self.project_ids = visible_project_ids(db, viewer) if viewer else None

    # ---- query helpers ----------------------------------------------------
    def _scope_tasks(self, query: Select) -> Select:
        if self.project_ids is not None:
            query = query.where(Task.project_id.in_(self.project_ids))
        if self.f.project_id:
            query = query.where(Task.project_id == self.f.project_id)
        return query

    def _entries(self, *columns) -> Select:
        query = select(*columns).select_from(TimeEntry).join(Task, TimeEntry.task_id == Task.id).where(
            TimeEntry.work_date >= self.f.start, TimeEntry.work_date <= self.f.end
        )
        if self.f.user_id:
            query = query.where(TimeEntry.user_id == self.f.user_id)
        return self._scope_tasks(query)

    def _done_in_period(self) -> Select:
        """(task_id, done_at) for tasks whose last move to Done is in the period."""
        query = (
            select(TaskStatusHistory.task_id, func.max(TaskStatusHistory.changed_at).label("done_at"))
            .join(Task, Task.id == TaskStatusHistory.task_id)
            .where(TaskStatusHistory.to_status == TaskStatus.DONE, Task.status == TaskStatus.DONE)
            .group_by(TaskStatusHistory.task_id)
            .having(and_(func.max(TaskStatusHistory.changed_at) >= self.f.start_dt,
                         func.max(TaskStatusHistory.changed_at) <= self.f.end_dt))
        )
        if self.f.user_id:
            query = query.where(Task.assignee_id == self.f.user_id)
        return self._scope_tasks(query)

    # ---- metrics -------------------------------------------------------------
    def total_hours(self) -> float:
        return round(float(self.db.scalar(self._entries(func.coalesce(func.sum(TimeEntry.hours), 0))) or 0), 1)

    def hours_by_user(self) -> list[tuple[str, float]]:
        rows = self.db.execute(
            self._entries(User.full_name, func.sum(TimeEntry.hours))
            .join(User, User.id == TimeEntry.user_id).group_by(User.full_name).order_by(func.sum(TimeEntry.hours).desc())
        )
        return [(name, round(hours, 1)) for name, hours in rows]

    def hours_by_project(self) -> list[tuple[str, float]]:
        rows = self.db.execute(
            self._entries(Project.key, func.sum(TimeEntry.hours))
            .join(Project, Project.id == Task.project_id).group_by(Project.key).order_by(Project.key)
        )
        return [(key, round(hours, 1)) for key, hours in rows]

    def hours_by_type(self) -> list[tuple[str, float]]:
        rows = self.db.execute(self._entries(Task.task_type, func.sum(TimeEntry.hours)).group_by(Task.task_type))
        return sorted(((str(t), round(h, 1)) for t, h in rows), key=lambda r: -r[1])

    def hours_by_week(self) -> list[tuple[str, float]]:
        totals: dict[date, float] = defaultdict(float)
        for work_date, hours in self.db.execute(self._entries(TimeEntry.work_date, TimeEntry.hours)):
            totals[work_date - timedelta(days=work_date.weekday())] += hours
        return [(f"{week:%d %b}", round(totals.get(week, 0.0), 1)) for week in self._weeks()]

    def hours_by_user_and_project(self) -> tuple[list[str], list[str], dict[tuple[str, str], float]]:
        rows = list(self.db.execute(
            self._entries(User.full_name, Project.key, func.sum(TimeEntry.hours))
            .join(User, User.id == TimeEntry.user_id).join(Project, Project.id == Task.project_id)
            .group_by(User.full_name, Project.key)
        ))
        users = sorted({r[0] for r in rows})
        projects = sorted({r[1] for r in rows})
        return users, projects, {(r[0], r[1]): round(r[2], 1) for r in rows}

    def _weeks(self) -> list[date]:
        first = self.f.start - timedelta(days=self.f.start.weekday())
        weeks = []
        while first <= self.f.end:
            weeks.append(first)
            first += timedelta(weeks=1)
        return weeks

    def tasks_completed(self) -> int:
        return len(list(self.db.execute(self._done_in_period())))

    def completed_by_week(self) -> list[tuple[str, int]]:
        counts: dict[date, int] = defaultdict(int)
        for _, done_at in self.db.execute(self._done_in_period()):
            day = done_at.date()
            counts[day - timedelta(days=day.weekday())] += 1
        return [(f"{week:%d %b}", counts.get(week, 0)) for week in self._weeks()]

    def cycle_time_days(self) -> float | None:
        done = dict(self.db.execute(self._done_in_period()).all())
        if not done:
            return None
        starts = dict(self.db.execute(
            select(TaskStatusHistory.task_id, func.min(TaskStatusHistory.changed_at))
            .where(TaskStatusHistory.task_id.in_(done), TaskStatusHistory.to_status == TaskStatus.IN_PROGRESS)
            .group_by(TaskStatusHistory.task_id)
        ).all())
        spans = [(done[t] - starts[t]).total_seconds() / 86400 for t in done if t in starts and done[t] >= starts[t]]
        return round(sum(spans) / len(spans), 1) if spans else None

    def estimate_vs_actual(self) -> dict:
        task_ids = [row[0] for row in self.db.execute(self._done_in_period())]
        if not task_ids:
            return {"estimate": 0.0, "actual": 0.0, "ratio": None, "tasks": []}
        tasks = self.db.scalars(
            select(Task).options(joinedload(Task.project)).where(Task.id.in_(task_ids), Task.estimate_hours.is_not(None))
        ).all()
        actuals = dict(self.db.execute(
            select(TimeEntry.task_id, func.sum(TimeEntry.hours)).where(TimeEntry.task_id.in_(task_ids))
            .group_by(TimeEntry.task_id)
        ).all())
        rows = [(t, t.estimate_hours or 0.0, round(actuals.get(t.id, 0.0), 1)) for t in tasks]
        estimate = round(sum(r[1] for r in rows), 1)
        actual = round(sum(r[2] for r in rows), 1)
        rows.sort(key=lambda r: abs(r[2] - r[1]), reverse=True)
        return {"estimate": estimate, "actual": actual,
                "ratio": round(actual / estimate, 2) if estimate else None, "tasks": rows[:10]}

    def utilisation(self) -> list[dict]:
        hours = dict(self.db.execute(
            self._entries(TimeEntry.user_id, func.sum(TimeEntry.hours)).group_by(TimeEntry.user_id)
        ).all())
        if not hours:
            return []
        users = self.db.scalars(select(User).where(User.id.in_(hours))).all()
        out = []
        for user in sorted(users, key=lambda u: u.full_name):
            capacity = (user.weekly_capacity_hours or 40) * self.f.weeks
            out.append({"user": user, "hours": round(hours[user.id], 1), "capacity": round(capacity, 1),
                        "percent": round(hours[user.id] / capacity * 100, 1) if capacity else 0})
        return out

    def overdue_tasks(self, limit: int = 20) -> list[Task]:
        query = self._scope_tasks(
            select(Task).options(joinedload(Task.project), joinedload(Task.assignee))
            .where(Task.due_date < date.today(), Task.status != TaskStatus.DONE).order_by(Task.due_date)
        )
        if self.f.user_id:
            query = query.where(Task.assignee_id == self.f.user_id)
        return list(self.db.scalars(query.limit(limit)))

    def overdue_count(self) -> int:
        query = self._scope_tasks(
            select(func.count(Task.id)).where(Task.due_date < date.today(), Task.status != TaskStatus.DONE)
        )
        if self.f.user_id:
            query = query.where(Task.assignee_id == self.f.user_id)
        return self.db.scalar(query) or 0

    def status_breakdown(self) -> list[tuple[str, int]]:
        query = self._scope_tasks(select(Task.status, func.count(Task.id)).group_by(Task.status))
        if self.f.user_id:
            query = query.where(Task.assignee_id == self.f.user_id)
        counts = {str(s): c for s, c in self.db.execute(query)}
        return [(str(s), counts.get(str(s), 0)) for s in TaskStatus]

    def open_tasks(self) -> int:
        return sum(c for s, c in self.status_breakdown() if s != TaskStatus.DONE)

    def burndown(self) -> list[tuple[str, int]]:
        """Open tasks at the end of each day of the period (created minus completed)."""
        query = self._scope_tasks(select(Task.id, Task.created_at))
        created = dict(self.db.execute(query).all())
        if not created:
            return []
        done_rows = self.db.execute(
            select(TaskStatusHistory.task_id, TaskStatusHistory.to_status, TaskStatusHistory.changed_at)
            .where(TaskStatusHistory.task_id.in_(created)).order_by(TaskStatusHistory.changed_at)
        )
        status_changes: dict[int, list[tuple[datetime, bool]]] = defaultdict(list)
        for task_id, to_status, changed_at in done_rows:
            status_changes[task_id].append((changed_at, to_status == TaskStatus.DONE))
        points = []
        day = self.f.start
        while day <= self.f.end:
            cutoff = datetime.combine(day, time.max)
            open_count = 0
            for task_id, created_at in created.items():
                if created_at and created_at > cutoff:
                    continue
                last = [is_done for at, is_done in status_changes[task_id] if at <= cutoff]
                if not (last and last[-1]):
                    open_count += 1
            points.append((f"{day:%d %b}", open_count))
            day += timedelta(days=1)
        return points

    def ai_adoption(self) -> dict:
        query = select(AIGenerationLog.outcome, func.count(AIGenerationLog.id)).where(
            AIGenerationLog.created_at >= self.f.start_dt, AIGenerationLog.created_at <= self.f.end_dt
        ).group_by(AIGenerationLog.outcome)
        if self.f.user_id:
            query = query.where(AIGenerationLog.user_id == self.f.user_id)
        counts = {outcome or "pending": c for outcome, c in self.db.execute(query)}
        reviewed = counts.get("accepted", 0) + counts.get("edited", 0) + counts.get("rejected", 0)
        used = counts.get("accepted", 0) + counts.get("edited", 0)
        ai_reqs = self.db.scalar(self._scope_req(select(func.count(Requirement.id)).where(Requirement.source == "AI"))) or 0
        all_reqs = self.db.scalar(self._scope_req(select(func.count(Requirement.id)))) or 0
        return {
            "generations": sum(counts.values()),
            "counts": counts,
            "rate": round(used / reviewed * 100, 1) if reviewed else None,
            "ai_requirements_percent": round(ai_reqs / all_reqs * 100, 1) if all_reqs else None,
        }

    def _scope_req(self, query: Select) -> Select:
        if self.project_ids is not None:
            query = query.where(Requirement.project_id.in_(self.project_ids))
        if self.f.project_id:
            query = query.where(Requirement.project_id == self.f.project_id)
        return query

    def summary(self) -> dict:
        utilisation = self.utilisation()
        team_percent = None
        if utilisation:
            team_percent = round(sum(u["hours"] for u in utilisation) / sum(u["capacity"] for u in utilisation) * 100, 1)
        return {
            "total_hours": self.total_hours(),
            "tasks_completed": self.tasks_completed(),
            "open_tasks": self.open_tasks(),
            "overdue": self.overdue_count(),
            "cycle_time_days": self.cycle_time_days(),
            "utilisation_percent": team_percent,
            "estimate_vs_actual": self.estimate_vs_actual(),
            "ai": self.ai_adoption(),
        }

    def charts(self) -> dict:
        """Data for Chart.js, as plain lists (rendered into a JSON script tag)."""
        def split(rows):
            return {"labels": [r[0] for r in rows], "values": [r[1] for r in rows]}

        return {
            "hours_by_week": split(self.hours_by_week()),
            "completed_by_week": split(self.completed_by_week()),
            "hours_by_user": split(self.hours_by_user()),
            "hours_by_project": split(self.hours_by_project()),
            "hours_by_type": split(self.hours_by_type()),
            "status": split(self.status_breakdown()),
            "burndown": split(self.burndown()),
        }

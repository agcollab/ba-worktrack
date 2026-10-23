"""Timesheet page, manual time entries and the start / stop timer."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import csrf_protect, get_current_user
from app.models import TaskStatus, User
from app.routers.forms import redirect, safe_next, to_date, to_float, to_int
from app.services import tasks as task_service
from app.services import time_tracking
from app.services.errors import ServiceError
from app.services.tasks import TaskFilters
from app.services.users import get_user, list_users
from app.templating import render, toast

router = APIRouter(tags=["time"], dependencies=[Depends(csrf_protect)], include_in_schema=False)


@router.get("/timesheet")
def timesheet(request: Request, week: str | None = None, user_id: str | None = None,
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start = time_tracking.week_start(to_date(week) or date.today())
    subject = user
    if to_int(user_id) and to_int(user_id) != user.id:
        if not user.is_manager:
            raise ServiceError("Only PMs and admins can view other people's timesheets.")
        subject = get_user(db, to_int(user_id))
    sheet = time_tracking.build_timesheet(db, subject, start)
    my_tasks = [t for t in task_service.search_tasks(db, user, TaskFilters(assignee_id=user.id, sort="updated"))
                if t.status != TaskStatus.DONE]
    others = task_service.search_tasks(db, user, TaskFilters(sort="updated"), limit=200)
    seen = {t.id for t in my_tasks}
    task_options = my_tasks + [t for t in others if t.id not in seen]
    team = []
    if user.is_manager:
        team = list_users(db, include_inactive=False)
    return render(request, "time/timesheet.html", {
        "sheet": sheet, "subject": subject, "task_options": task_options, "team": team,
        "prev_week": start - timedelta(weeks=1), "next_week": start + timedelta(weeks=1),
        "this_week": time_tracking.week_start(date.today()),
        "timer": time_tracking.running_timer(db, user), "editable": subject.id == user.id,
    })


@router.post("/time")
def log_time(request: Request, task_id: str = Form(...), work_date: str = Form(...), hours: str = Form(...),
             note: str = Form(""), next: str = Form("/timesheet"),
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, to_int(task_id) or 0)
    day = to_date(work_date) or date.today()
    entry = time_tracking.log_time(db, user, task, day, to_float(hours) or 0, note)
    db.commit()
    return redirect(safe_next(next, "/timesheet"), f"Logged {entry.hours:g} h on {task.key}.")


@router.post("/time/{entry_id}/edit")
def edit_entry(entry_id: int, work_date: str = Form(...), hours: str = Form(...), note: str = Form(""),
               next: str = Form("/timesheet"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = time_tracking.get_entry(db, user, entry_id)
    time_tracking.update_entry(db, user, entry, to_date(work_date) or entry.work_date, to_float(hours) or 0, note)
    db.commit()
    return redirect(safe_next(next, "/timesheet"), "Time entry updated.")


@router.post("/time/{entry_id}/delete")
def delete_entry(entry_id: int, next: str = Form("/timesheet"), user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    entry = time_tracking.get_entry(db, user, entry_id)
    time_tracking.delete_entry(db, user, entry)
    db.commit()
    return redirect(safe_next(next, "/timesheet"), "Time entry deleted.")


@router.post("/timer/start")
def start_timer(request: Request, task_id: str = Form(...), note: str = Form(""),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, to_int(task_id) or 0)
    _, stopped = time_tracking.start_timer(db, user, task, note or None)
    db.commit()
    message = f"Timer started on {task.key}."
    if stopped:
        message += f" Logged {stopped.hours:g} h on the previous task."
    return _timer_response(request, db, user, message)


@router.post("/timer/stop")
def stop_timer(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = time_tracking.stop_timer(db, user)
    db.commit()
    message = f"Logged {entry.hours:g} h." if entry else "Timer stopped (under a minute, nothing logged)."
    return _timer_response(request, db, user, message)


def _timer_response(request: Request, db: Session, user: User, message: str):
    if request.headers.get("hx-request"):
        response = render(request, "time/_timer.html", {"timer": time_tracking.running_timer(db, user)})
        return toast(response, message)
    return redirect(request.headers.get("referer") or "/timesheet", message)

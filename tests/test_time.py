"""Time entries, the 24-hour rule, the timer and the weekly timesheet."""
from datetime import date, datetime, timedelta

import pytest

from app.models import RunningTimer, TimeEntry
from app.services import tasks as task_service
from app.services import time_tracking
from app.services.errors import ServiceError
from tests.conftest import form, login


@pytest.fixture
def task(db, people):
    t = task_service.create_task(db, people["pm"], people["pay"].id, "Run UAT", assignee_id=people["asha"].id)
    db.commit()
    return t


def test_log_time_through_the_form(client, db, people, task):
    login(client, "asha@test.com")
    client.post("/time", data=form(client, task_id=task.id, work_date=date.today().isoformat(), hours="2.5",
                                   note="Workshop"))
    entry = db.query(TimeEntry).one()
    assert entry.hours == 2.5 and entry.user_id == people["asha"].id


def test_max_24_hours_per_day(db, people, task):
    today = date.today()
    time_tracking.log_time(db, people["asha"], task, today, 20)
    with pytest.raises(ServiceError, match="more than 24 h"):
        time_tracking.log_time(db, people["asha"], task, today, 5)


def test_no_future_or_zero_hours(db, people, task):
    with pytest.raises(ServiceError):
        time_tracking.log_time(db, people["asha"], task, date.today() + timedelta(days=1), 1)
    with pytest.raises(ServiceError):
        time_tracking.log_time(db, people["asha"], task, date.today(), 0)


def test_ba_cannot_edit_someone_elses_entry(db, people, task):
    entry = time_tracking.log_time(db, people["asha"], task, date.today(), 1)
    with pytest.raises(ServiceError):
        time_tracking.get_entry(db, people["ben"], entry.id)


def test_timer_logs_rounded_hours(db, people, task):
    time_tracking.start_timer(db, people["asha"], task)
    timer = db.query(RunningTimer).one()
    timer.started_at = datetime.now() - timedelta(minutes=93)
    entry = time_tracking.stop_timer(db, people["asha"])
    assert entry.hours == 1.55  # 93 min rounded to 3-minute steps
    assert db.query(RunningTimer).count() == 0


def test_starting_a_second_timer_stops_the_first(db, people, task):
    other = task_service.create_task(db, people["pm"], people["pay"].id, "Other")
    time_tracking.start_timer(db, people["asha"], task)
    db.query(RunningTimer).one().started_at = datetime.now() - timedelta(minutes=30)
    _, stopped = time_tracking.start_timer(db, people["asha"], other)
    assert stopped.task_id == task.id and stopped.hours == 0.5
    assert db.query(RunningTimer).one().task_id == other.id


def test_timer_via_htmx(client, db, people, task):
    login(client, "asha@test.com")
    response = client.post("/timer/start", data={"task_id": task.id},
                           headers={"HX-Request": "true", "X-CSRF-Token": client.csrf})
    assert "data-timer-started" in response.text
    response = client.post("/timer/stop", headers={"HX-Request": "true", "X-CSRF-Token": client.csrf})
    assert "toast" in response.headers["hx-trigger"]


def test_weekly_timesheet(client, db, people, task):
    monday = time_tracking.week_start(date.today())
    time_tracking.log_time(db, people["asha"], task, monday, 3)
    db.commit()
    sheet = time_tracking.build_timesheet(db, people["asha"], date.today())
    assert sheet.total == 3 and sheet.day_totals[monday] == 3
    login(client, "asha@test.com")
    assert "Run UAT" in client.get("/timesheet").text


def test_ba_cannot_view_other_timesheets(client, people):
    login(client, "asha@test.com")
    assert client.get(f"/timesheet?user_id={people['ben'].id}").status_code == 400
